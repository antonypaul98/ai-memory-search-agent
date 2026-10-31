"""Real-PostgreSQL authenticated capture API acceptance, without camera hardware.

The API and a separate revoker use independent registry instances against one
isolated schema. This is not physical camera or trusted object-identity proof.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.auth import get_current_user
from app.config import Settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.models.user import UserPublic
from app.services.home_agent.image_ingest import DetectedObject
from app.services.home_agent.postgres_capture_registry import PostgresCaptureSessionRegistry


@pytest.fixture
def capture_api_database(monkeypatch):
    dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real PostgreSQL DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "home_api_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    alias = "HOME_API_DSN_" + uuid4().hex
    monkeypatch.setenv(alias, make_conninfo(dsn, options=f"-c search_path={schema}"))
    factory = get_postgres_connection_factory(
        Settings(_env_file=None, postgres_dsn_env=alias)
    )
    try:
        yield factory
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)
            ))


class _FixtureDetector:
    detector_id = "synthetic-api-postgres"

    def detect(self, image):
        return [DetectedObject("keys", 0.96, (0.1, 0.1, 0.8, 0.8))]


def _png():
    buffer = BytesIO()
    Image.new("RGB", (32, 32), (20, 30, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _counts(factory):
    with factory() as conn:
        return (
            conn.execute("SELECT COUNT(*) AS n FROM home_image_evidence").fetchone()["n"],
            conn.execute("SELECT COUNT(*) AS n FROM home_object_sightings").fetchone()["n"],
        )


def test_authenticated_api_cross_worker_capture_revocation_and_tenant_isolation(
    capture_api_database, test_settings,
):
    """Both HTTP capture paths must use shared, transaction-guarded PostgreSQL."""
    from app.main import app
    from app.api import dependencies as home_dependencies
    from app.api import home_image_dependencies as image_dependencies

    factory = capture_api_database
    identity = {"user_id": "house-a"}
    app.dependency_overrides[get_current_user] = lambda: UserPublic(
        user_id=identity["user_id"], display_name="Synthetic Home",
    )
    try:
        with (
            patch.object(home_dependencies, "get_postgres_connection_factory", lambda _: factory),
            patch.object(image_dependencies, "get_postgres_connection_factory", lambda _: factory),
            patch.object(home_dependencies, "get_settings", lambda: test_settings),
            patch.object(image_dependencies, "get_settings", lambda: test_settings),
            patch.object(image_dependencies, "LocalOwlViTDetector", lambda *a, **k: _FixtureDetector()),
            patch("app.main.get_settings", lambda: test_settings),
            TestClient(app) as client,
        ):
            start = client.post(
                "/api/v1/home-agent/capture-sessions",
                json={"source_id": "camera-a", "ttl_seconds": 180},
            )
            assert start.status_code == 200, start.text
            session_id = start.json()["session_id"]
            observed_at = datetime.now(timezone.utc).isoformat()
            detection = {
                "session_id": session_id, "source_id": "camera-a",
                "object_name": "keys", "location": "office",
                "observed_at": observed_at, "confidence": 0.96,
                "evidence_id": "structured-api-1",
            }
            image_params = {
                "session_id": session_id, "source_id": "camera-a",
                "location": "office", "observed_at": observed_at,
            }
            structured = client.post(
                "/api/v1/home-agent/capture-detections", json=detection,
            )
            assert structured.status_code == 200, structured.text
            assert structured.json() == {"stored": True}
            assert client.post(
                "/api/v1/home-agent/capture-detections", json=detection,
            ).json() == {"stored": False}

            image = client.post(
                "/api/v1/home-agent/capture-images",
                params=image_params, content=_png(),
            )
            assert image.status_code == 200, image.text
            assert image.json()["stored"] is True
            assert image.json()["frame_id"]
            duplicate = client.post(
                "/api/v1/home-agent/capture-images",
                params=image_params, content=_png(),
            )
            assert duplicate.status_code == 200, duplicate.text
            assert duplicate.json()["stored"] is False
            retained = _counts(factory)
            assert retained[0] == 1 and retained[1] >= 1

            identity["user_id"] = "house-b"
            assert client.post(
                "/api/v1/home-agent/capture-detections",
                json={**detection, "evidence_id": "cross-tenant"},
            ).status_code == 403
            assert client.post(
                "/api/v1/home-agent/capture-images",
                params=image_params, content=_png(),
            ).status_code == 403
            assert _counts(factory) == retained

            identity["user_id"] = "house-a"
            # A second worker revokes the session in the same database.
            assert PostgresCaptureSessionRegistry(factory).revoke(session_id=session_id)
            assert client.post(
                "/api/v1/home-agent/capture-detections",
                json={**detection, "evidence_id": "after-revocation"},
            ).status_code == 403
            assert client.post(
                "/api/v1/home-agent/capture-images",
                params=image_params, content=_png(),
            ).status_code == 403
            assert _counts(factory) == retained
    finally:
        app.dependency_overrides.clear()


def test_authenticated_capture_erasure_fences_future_http_writes(
    capture_api_database, test_settings,
):
    """Erasing one tenant removes sessions/evidence and prevents HTTP resurrection."""
    from app.main import app
    from app.api import dependencies as home_dependencies
    from app.api import home_image_dependencies as image_dependencies
    from app.db.account_erasure_fence import AccountErasureFence
    from app.db.home_physical_privacy import delete_user_home_physical_data

    factory = capture_api_database
    identity = {"user_id": "erased-home"}
    app.dependency_overrides[get_current_user] = lambda: UserPublic(
        user_id=identity["user_id"], display_name="Synthetic Home",
    )
    try:
        with (
            patch.object(home_dependencies, "get_postgres_connection_factory", lambda _: factory),
            patch.object(image_dependencies, "get_postgres_connection_factory", lambda _: factory),
            patch.object(home_dependencies, "get_settings", lambda: test_settings),
            patch.object(image_dependencies, "get_settings", lambda: test_settings),
            patch.object(image_dependencies, "LocalOwlViTDetector", lambda *a, **k: _FixtureDetector()),
            patch("app.main.get_settings", lambda: test_settings),
            TestClient(app) as client,
        ):
            sessions = {}
            params = {}
            for user_id in ("erased-home", "neighbor-home"):
                identity["user_id"] = user_id
                source_id = "camera-" + user_id
                start = client.post(
                    "/api/v1/home-agent/capture-sessions",
                    json={"source_id": source_id, "ttl_seconds": 180},
                )
                assert start.status_code == 200, start.text
                sessions[user_id] = start.json()["session_id"]
                params[user_id] = {
                    "session_id": sessions[user_id], "source_id": source_id,
                    "location": "office",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
                image = client.post(
                    "/api/v1/home-agent/capture-images",
                    params=params[user_id], content=_png(),
                )
                assert image.status_code == 200, image.text
                assert image.json()["stored"] is True
                detection = client.post(
                    "/api/v1/home-agent/capture-detections",
                    json={
                        **params[user_id], "object_name": "keys",
                        "confidence": 0.96, "evidence_id": "structured-" + user_id,
                    },
                )
                assert detection.status_code == 200, detection.text
                assert detection.json() == {"stored": True}

            assert _counts(factory) == (2, 4)
            AccountErasureFence(factory).fence(user_id="erased-home")
            erased = delete_user_home_physical_data(factory, user_id="erased-home")
            assert erased["capture_sessions"] == 1
            assert erased["image_evidence"] == 1
            assert erased["sightings"] == 2
            with factory() as conn:
                for table in ("home_capture_sessions", "home_image_evidence", "home_object_sightings"):
                    assert conn.execute(
                        f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s",
                        ("erased-home",),
                    ).fetchone()["n"] == 0
                    assert conn.execute(
                        f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s",
                        ("neighbor-home",),
                    ).fetchone()["n"] >= 1

            identity["user_id"] = "erased-home"
            new_session = client.post(
                "/api/v1/home-agent/capture-sessions",
                json={"source_id": "camera-erased-home", "ttl_seconds": 180},
            )
            assert new_session.status_code == 403, new_session.text
            assert "account erasure" not in new_session.text
            assert client.post(
                "/api/v1/home-agent/capture-images",
                params=params["erased-home"], content=_png(),
            ).status_code == 403
            assert client.post(
                "/api/v1/home-agent/capture-detections",
                json={
                    **params["erased-home"], "object_name": "keys",
                    "confidence": 0.96, "evidence_id": "after-erasure",
                },
            ).status_code == 403
            assert _counts(factory) == (1, 2)
            identity["user_id"] = "neighbor-home"
            assert client.post(
                "/api/v1/home-agent/capture-images",
                params=params["neighbor-home"], content=_png(),
            ).status_code == 200
            assert _counts(factory) == (1, 2)
    finally:
        app.dependency_overrides.clear()

def test_synthetic_identity_proofs_link_http_frames_to_query_and_revoke(
    capture_api_database, test_settings,
):
    """Real PostgreSQL/HTTP integration with a STUB verifier, not identity acceptance.

    Camera images become class-only sightings. Only separately supplied,
    consented synthetic identity proofs may turn two sightings into a verified
    location-change response. Revocation must erase that association history.
    """
    from datetime import timedelta

    from app.main import app
    from app.api import dependencies as home_dependencies
    from app.api import home_image_dependencies as image_dependencies
    from app.db.postgres_home_image_store import PostgresHomeImageStore
    from app.services.home_agent.verified_identity_ingest import (
        InstanceIdentityConsent, VerifiedInstanceIngestService, VerifiedInstanceProof,
    )

    factory = capture_api_database
    identity = {"user_id": "verified-house"}
    source_id = "camera-verified"
    store = PostgresHomeImageStore(factory)
    store.grant_instance_identity_consent(
        user_id=identity["user_id"], source_id=source_id, ttl_seconds=180,
    )
    app.dependency_overrides[get_current_user] = lambda: UserPublic(
        user_id=identity["user_id"], display_name="Synthetic Home",
    )
    try:
        with (
            patch.object(home_dependencies, "get_postgres_connection_factory", lambda _: factory),
            patch.object(image_dependencies, "get_postgres_connection_factory", lambda _: factory),
            patch.object(home_dependencies, "get_settings", lambda: test_settings),
            patch.object(image_dependencies, "get_settings", lambda: test_settings),
            patch.object(image_dependencies, "LocalOwlViTDetector", lambda *a, **k: _FixtureDetector()),
            patch("app.main.get_settings", lambda: test_settings),
            TestClient(app) as client,
        ):
            started = client.post(
                "/api/v1/home-agent/capture-sessions",
                json={"source_id": source_id, "ttl_seconds": 180},
            )
            assert started.status_code == 200, started.text
            session_id = started.json()["session_id"]
            observations = []
            for location, color in (
                ("desk", (20, 30, 40)),
                ("kitchen", (40, 30, 20)),
                # Same detector class, independently identified second object.
                ("hallway", (20, 40, 30)),
            ):
                image = BytesIO()
                Image.new("RGB", (32, 32), color).save(image, format="PNG")
                response = client.post(
                    "/api/v1/home-agent/capture-images",
                    params={
                        "session_id": session_id, "source_id": source_id,
                        "location": location,
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    },
                    content=image.getvalue(),
                )
                assert response.status_code == 200, response.text
                assert response.json()["stored"] is True
                with factory() as conn:
                    observation = conn.execute(
                        """SELECT observation_id FROM home_image_observations
                           WHERE user_id=%s AND frame_id=%s""",
                        (identity["user_id"], response.json()["frame_id"]),
                    ).fetchone()
                assert observation is not None
                observations.append(observation["observation_id"])

            query = {"object_name": "keys"}
            endpoint = "/api/v1/home-agent/observed-location-changes"
            before_proof = client.post(endpoint, json=query)
            assert before_proof.status_code == 200, before_proof.text
            assert before_proof.json() == {"changes": []}

            # The fixture is an explicitly trusted TEST STUB. No model or
            # class-only matcher is promoted to a physical identity verifier.
            proofs = {
                observation_id: VerifiedInstanceProof(
                    user_id="verified-house", observation_id=observation_id,
                    source_id=source_id,
                    instance_id="keys-1" if index < 2 else "keys-2",
                    identity_evidence_id=f"synthetic-independent-{index}",
                    identity_confidence=0.99,
                )
                for index, observation_id in enumerate(observations)
            }

            class SyntheticVerifier:
                def verify(self, *, user_id, observation_id, source_id):
                    proof = proofs.get(observation_id)
                    assert proof is not None
                    assert proof.user_id == user_id and proof.source_id == source_id
                    return proof

            now = datetime.now(timezone.utc)
            consent = InstanceIdentityConsent(
                user_id="verified-house", source_id=source_id,
                granted_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(minutes=3),
            )
            ingest = VerifiedInstanceIngestService(
                verifier=SyntheticVerifier(), store=store,
            )
            # Two lookalike class sightings with different verified identities
            # cannot imply a physical relocation through the HTTP query.
            for observation_id in (observations[0], observations[2]):
                assert ingest.ingest(
                    user_id="verified-house", observation_id=observation_id,
                    source_id=source_id, consent=consent,
                    now=datetime.now(timezone.utc),
                )
            ambiguous = client.post(endpoint, json=query)
            assert ambiguous.status_code == 200, ambiguous.text
            assert ambiguous.json() == {"changes": []}

            # Only a second independently verified sighting of keys-1 can
            # establish an observed change; keys-2 remains a separate object.
            assert ingest.ingest(
                user_id="verified-house", observation_id=observations[1],
                source_id=source_id, consent=consent,
                now=datetime.now(timezone.utc),
            )

            linked = client.post(endpoint, json=query)
            assert linked.status_code == 200, linked.text
            changes = linked.json()["changes"]
            assert len(changes) == 1
            assert changes[0]["instance_id"] == "keys-1"
            assert (changes[0]["from_location"], changes[0]["to_location"]) == (
                "desk", "kitchen",
            )
            assert set((
                changes[0]["from_identity_evidence_id"],
                changes[0]["to_identity_evidence_id"],
            )) == {"synthetic-independent-0", "synthetic-independent-1"}

            identity["user_id"] = "other-house"
            isolated = client.post(endpoint, json=query)
            assert isolated.status_code == 200, isolated.text
            assert isolated.json() == {"changes": []}
            identity["user_id"] = "verified-house"

            assert store.revoke_instance_identity_consent(
                user_id="verified-house", source_id=source_id,
            ) == 3
            revoked = client.post(endpoint, json=query)
            assert revoked.status_code == 200, revoked.text
            assert revoked.json() == {"changes": []}
            with factory() as conn:
                assert conn.execute(
                    "SELECT COUNT(*) AS n FROM home_object_sightings WHERE user_id=%s",
                    ("verified-house",),
                ).fetchone()["n"] == 3
    finally:
        app.dependency_overrides.clear()

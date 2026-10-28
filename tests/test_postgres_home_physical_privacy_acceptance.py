"""Real-Postgres acceptance for Home physical-memory tenant erasure.

This proves retained image bytes and all relational Home memory are erased for one
tenant without touching a neighboring tenant.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.home_physical_privacy import delete_user_home_physical_data, export_user_home_physical_data
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.postgres_capture_registry import PostgresCaptureSessionRegistry
from app.services.home_agent.image_ingest import ImageObservationBatch, DetectedObject, canonical_id


def test_home_physical_erasure_is_exact_tenant_and_removes_retained_bytes(monkeypatch):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    schema = "home_privacy_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "HOME_PRIVACY_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    settings = Settings(_env_file=None, postgres_dsn_env=dsn_alias)
    factory = get_postgres_connection_factory(settings)
    store = PostgresHomeImageStore(factory)
    registry = PostgresCaptureSessionRegistry(factory)
    observed_at = datetime(2026, 9, 16, 7, 30, tzinfo=timezone.utc)

    users = ("home-privacy-owner", "home-privacy-neighbor")
    frames: dict[str, str] = {}
    observations: dict[str, str] = {}
    retained: dict[str, bytes] = {}
    sessions: dict[str, CaptureSession] = {}
    try:
        session_start = datetime.now(timezone.utc) - timedelta(seconds=2)
        for user_id in users:
            session = CaptureSession(
                session_id=uuid4().hex, user_id=user_id, source_id="camera-1",
                started_at=session_start, expires_at=session_start + timedelta(minutes=5),
            )
            registry.register(session)
            sessions[user_id] = session
        for user_id in users:
            image_bytes = ("private-image-" + user_id).encode()
            digest = hashlib.sha256(image_bytes).hexdigest()
            frame_id = canonical_id("frame", user_id, digest, "camera-1", "kitchen", observed_at.isoformat())
            detection = DetectedObject("keys", 0.94, (0.1, 0.2, 0.4, 0.6))
            batch = ImageObservationBatch(
                user_id=user_id, frame_id=frame_id, image_bytes=image_bytes,
                image_sha256=digest, source_id="camera-1", location="kitchen",
                observed_at=observed_at, detector_id="fixture-detector", detections=(detection,),
            )
            assert store.store_image_batch(batch)["stored_observations"] == 1
            frames[user_id] = frame_id
            retained[user_id] = image_bytes
            observations[user_id] = canonical_id(
                "observation", frame_id, detection.object_class, "[0.1, 0.2, 0.4, 0.6]"
            )

        # Seed optional identity records directly to prove erasure, without
        # claiming a real verifier or camera acceptance.
        with factory() as conn:
            for user_id in users:
                conn.execute("""
                    INSERT INTO home_instance_identity_consents
                        (user_id, source_id, granted_at, expires_at)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, "camera-1", observed_at, observed_at + timedelta(days=100)))
                conn.execute("""
                    INSERT INTO home_verified_instance_associations
                        (user_id, observation_id, instance_id,
                         identity_evidence_id, identity_confidence)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, observations[user_id], f"keys-{user_id}",
                      f"identity-proof-{user_id}", 0.97))

        for user_id in users:
            exported = export_user_home_physical_data(factory, user_id=user_id)
            assert len(exported["verified_instance_associations"]) == 1
            assert len(exported["instance_identity_consents"]) == 1
            assert [row["session_id"] for row in exported["capture_sessions"]] == [sessions[user_id].session_id]
            assert "image_bytes" not in exported["image_evidence"][0]
            assert exported["verified_instance_associations"][0]["identity_evidence_id"] == f"identity-proof-{user_id}"

        assert store.get_image(user_id=users[0], frame_id=frames[users[0]]) == retained[users[0]]
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) == retained[users[1]]

        assert delete_user_home_physical_data(factory, user_id=users[0]) == {
            "capture_sessions": 1, "verified_instance_associations": 1, "instance_identity_consents": 1,
            "image_observations": 1, "image_evidence": 1,
            "physical_objects": 1, "sightings": 1,
        }
        assert store.get_image(user_id=users[0], frame_id=frames[users[0]]) is None
        assert store.describe_observation(user_id=users[0], observation_id=observations[users[0]]) is None

        # Neighbor evidence, identity grant, canonical relation, and bytes survive.
        with factory() as conn:
            for table in ("home_capture_sessions", "home_instance_identity_consents", "home_verified_instance_associations"):
                assert conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s",
                                    (users[0],)).fetchone()["n"] == 0
                assert conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s",
                                    (users[1],)).fetchone()["n"] == 1
        with pytest.raises(PermissionError):
            registry.resolve(session_id=sessions[users[0]].session_id,
                             user_id=users[0], source_id="camera-1")
        assert registry.resolve(session_id=sessions[users[1]].session_id,
                                user_id=users[1], source_id="camera-1") == sessions[users[1]]
        # Neighbor evidence, canonical relation, and exact retained bytes survive unchanged.
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) == retained[users[1]]
        assert store.describe_observation(user_id=users[1], observation_id=observations[users[1]]) is not None

        # Repeated erasure is idempotent and cannot spill into the neighboring tenant.
        assert delete_user_home_physical_data(factory, user_id=users[0]) == {
            "capture_sessions": 0, "verified_instance_associations": 0, "instance_identity_consents": 0,
            "image_observations": 0, "image_evidence": 0,
            "physical_objects": 0, "sightings": 0,
        }
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) == retained[users[1]]
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))

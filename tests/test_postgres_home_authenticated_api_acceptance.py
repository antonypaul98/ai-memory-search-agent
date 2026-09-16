"""Real-Postgres acceptance for authenticated Home Agent query/evidence HTTP paths."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.config import Settings, get_settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.models.user import UserPublic
from app.services.home_agent import HomeAgentQueryService
from app.services.home_agent.image_ingest import DetectedObject, ImageObservationBatch, canonical_id


def test_authenticated_http_query_and_evidence_are_real_postgres_tenant_isolated(monkeypatch):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from app.main import app

    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    schema = "home_auth_api_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "HOME_AUTH_API_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    settings = Settings(_env_file=None, postgres_dsn_env=dsn_alias)
    store = PostgresHomeImageStore(get_postgres_connection_factory(settings))
    service = HomeAgentQueryService(store)
    owner = "home-api-owner"
    neighbor = "home-api-neighbor"
    owner_bytes = b"owner-private-keys-frame"

    def observe(user_id: str, location: str, image_bytes: bytes, confidence: float) -> str:
        when = datetime(2026, 9, 16, 15, 30, tzinfo=timezone.utc)
        digest = hashlib.sha256(image_bytes).hexdigest()
        frame_id = canonical_id("frame", user_id, digest, "camera-entry", location, when.isoformat())
        detection = DetectedObject("keys", confidence, (0.1, 0.2, 0.4, 0.6))
        batch = ImageObservationBatch(
            user_id=user_id, frame_id=frame_id, image_bytes=image_bytes, image_sha256=digest,
            source_id="camera-entry", location=location, observed_at=when,
            detector_id="fixture-detector", detections=(detection,),
        )
        assert store.store_image_batch(batch)["stored_observations"] == 1
        return frame_id

    try:
        owner_frame = observe(owner, "entry table", owner_bytes, 0.96)
        observe(neighbor, "neighbor bedroom", b"neighbor-private-frame", 0.99)
        current_user = {"id": owner}

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_home_agent_query_service] = lambda: service
        app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id=current_user["id"])
        with TestClient(app) as client:
            answer = client.post("/api/v1/home-agent/where-is", json={"object_name": "KEYS", "min_confidence": 0.9})
            assert answer.status_code == 200
            payload = answer.json()
            assert payload["location"] == "entry table"
            assert payload["evidence_frame_id"] == owner_frame
            assert "neighbor bedroom" not in payload["text"]

            evidence = client.get(f"/api/v1/home-agent/evidence/{owner_frame}")
            assert evidence.status_code == 200
            assert evidence.content == owner_bytes

            current_user["id"] = neighbor
            denied = client.get(f"/api/v1/home-agent/evidence/{owner_frame}")
            assert denied.status_code == 404
            assert denied.content != owner_bytes
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))

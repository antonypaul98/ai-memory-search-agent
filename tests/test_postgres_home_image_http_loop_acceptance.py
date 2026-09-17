"""Real-Postgres acceptance for authenticated image -> memory -> evidence HTTP loop."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.api.home_image_dependencies import get_home_agent_authenticated_image_ingest
from app.config import Settings, get_settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.models.user import UserPublic
from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.image_ingest import DetectedObject, HomeImageIngestService
from app.services.home_agent.query_service import HomeAgentQueryService
from tests.test_home_agent_image_ingest import image_bytes


class FixtureDetector:
    detector_id = "fixture-not-a-trained-detector"

    def detect(self, image):
        assert image.size == (24, 16)
        return [DetectedObject("keys", 0.96, (0.1, 0.2, 0.4, 0.6))]


def test_authenticated_image_http_loop_is_real_postgres_and_tenant_isolated(monkeypatch):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from app.main import app

    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    schema = "home_image_http_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "HOME_IMAGE_HTTP_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    settings = Settings(_env_file=None, postgres_dsn_env=dsn_alias)
    store = PostgresHomeImageStore(get_postgres_connection_factory(settings))
    registry = CaptureSessionRegistry()
    ingest = AuthenticatedHomeImageIngest(
        registry=registry,
        image_ingest=HomeImageIngestService(store, FixtureDetector()),
    )
    query = HomeAgentQueryService(store)
    owner, neighbor = "home-loop-owner", "home-loop-neighbor"
    current_user = {"id": owner}
    now = datetime.now(timezone.utc)
    session = CaptureSession(
        session_id="owner-capture",
        user_id=owner,
        source_id="camera-entry",
        started_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=4),
    )
    registry.register(session)

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_home_agent_authenticated_image_ingest] = lambda: ingest
    app.dependency_overrides[get_home_agent_query_service] = lambda: query
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id=current_user["id"])

    try:
        params = urlencode({
            "session_id": session.session_id,
            "source_id": session.source_id,
            "location": "entry table",
            "observed_at": now.isoformat(),
        })
        with TestClient(app) as client:
            captured = client.post(
                f"/api/v1/home-agent/capture-images?{params}",
                content=image_bytes(),
                headers={"content-type": "application/octet-stream"},
            )
            assert captured.status_code == 200
            frame_id = captured.json()["frame_id"]
            assert captured.json()["stored_observations"] == 1

            answer = client.post("/api/v1/home-agent/where-is", json={"object_name": "KEYS"})
            assert answer.status_code == 200
            assert answer.json()["location"] == "entry table"
            assert answer.json()["evidence_frame_id"] == frame_id

            evidence = client.get(f"/api/v1/home-agent/evidence/{frame_id}")
            assert evidence.status_code == 200
            owner_evidence = evidence.content
            assert owner_evidence

            current_user["id"] = neighbor
            denied = client.get(f"/api/v1/home-agent/evidence/{frame_id}")
            assert denied.status_code == 404
            assert denied.content != owner_evidence
            neighbor_answer = client.post("/api/v1/home-agent/where-is", json={"object_name": "keys"})
            assert neighbor_answer.status_code == 404
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))

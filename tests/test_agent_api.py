"""Agent status API and schema v5 tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.schema import SCHEMA_VERSION, migrate
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.services.agent_status_service import AgentStatusService


class TestSchemaV5:
    def test_migrates_to_v5(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "v5.db"))
        migrate(settings)
        import sqlite3

        conn = sqlite3.connect(settings.sqlite_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(captures)").fetchall()}
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert version == SCHEMA_VERSION
        assert SCHEMA_VERSION >= 5
        assert "stage" in cols
        assert "agent_search_events" in tables


class TestAgentStatusAPI:
    def test_agent_status_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/agent/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert "memory_count" in data
        assert "pending_captures" in data
        assert "today_saves" in data
        assert "recent_searches" in data
        assert data["user_id"] == LOCAL_DEFAULT_USER_ID

    def test_record_search_appears_in_status(self, test_settings: Settings) -> None:
        service = AgentStatusService(test_settings)
        user = UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Demo")
        service.record_search(user_id=user.user_id, query="MCP servers")
        status = service.get_status(user)
        assert any(s.query == "MCP servers" for s in status.recent_searches)


class TestCaptureAsyncAPI:
    def test_youtube_returns_queued_immediately(self, client: TestClient) -> None:
        with patch("app.services.capture_service.IngestService") as mock_ingest:
            instance = mock_ingest.return_value
            instance.ingest_single_url.return_value = MagicMock(
                success=True, skipped=False, error=None, title="Demo"
            )
            resp = client.post(
                "/api/v1/capture/url",
                json={
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "title": "Demo",
                    "async_processing": True,
                    "observed": {
                        "platform": "youtube",
                        "creator": "Demo Channel",
                        "video_id": "dQw4w9WgXcQ",
                    },
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "queued"
            assert body["stage"] == "queued"
            assert body["capture_id"]
            assert "Added to Memory" in body["message"]

            # Poll status endpoint
            status = client.get(f"/api/v1/capture/status/{body['capture_id']}")
            assert status.status_code == 200
            assert status.json()["capture_id"] == body["capture_id"]

    def test_retry_endpoint(self, client: TestClient) -> None:
        with patch("app.services.capture_service.IngestService") as mock_ingest:
            instance = mock_ingest.return_value
            instance.ingest_single_url.return_value = MagicMock(
                success=False, skipped=False, error="boom", title=None
            )
            created = client.post(
                "/api/v1/capture/url",
                json={
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "title": "Demo",
                    "async_processing": False,
                },
            )
            assert created.status_code == 200
            capture_id = created.json()["capture_id"]
            assert created.json()["status"] == "failed"

            instance.ingest_single_url.return_value = MagicMock(
                success=True, skipped=False, error=None, title="Demo"
            )
            retried = client.post(f"/api/v1/capture/retry/{capture_id}")
            assert retried.status_code == 200
            # async retry for youtube with async_processing from payload (True default)
            assert retried.json()["capture_id"] == capture_id

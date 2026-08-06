"""Tests for ingest and search API validation."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings, get_ingest_service, get_search_service
from app.config import Settings, get_settings
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.models.video import (
    IngestResponse,
    IngestResultItem,
    SearchResponse,
    SearchResultItem,
)
from app.services.ingest_service import IngestService, MAX_BATCH_SIZE


def _demo_user() -> UserPublic:
    return UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Local Demo User")


@pytest.fixture
def api_client(test_settings: Settings) -> TestClient:
    from app.main import app

    mock_ingest = MagicMock(spec=IngestService)
    mock_search = MagicMock()

    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = _demo_user
    app.dependency_overrides[get_ingest_service] = lambda: mock_ingest
    app.dependency_overrides[get_search_service] = lambda: mock_search

    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as client:
            client.mock_ingest = mock_ingest
            client.mock_search = mock_search
            yield client

    app.dependency_overrides.clear()


class TestIngestAPI:
    def test_ingest_batch_success(self, api_client: TestClient) -> None:
        api_client.mock_ingest.ingest_batch.return_value = IngestResponse(
            total=1,
            succeeded=1,
            failed=0,
            results=[
                IngestResultItem(
                    url="https://youtu.be/dQw4w9WgXcQ",
                    success=True,
                    video_id="dQw4w9WgXcQ",
                    title="Demo",
                    chunk_count=3,
                )
            ],
        )
        response = api_client.post(
            "/api/v1/videos/ingest",
            json={"urls": ["https://youtu.be/dQw4w9WgXcQ"]},
        )
        assert response.status_code == 200
        assert response.json()["succeeded"] == 1

    def test_ingest_rejects_batch_over_limit(self, api_client: TestClient) -> None:
        urls = ["https://youtu.be/dQw4w9WgXcQ"] * (MAX_BATCH_SIZE + 1)
        response = api_client.post("/api/v1/videos/ingest", json={"urls": urls})
        assert response.status_code == 400
        assert "Batch limit" in response.json()["detail"]

    def test_ingest_requires_urls(self, api_client: TestClient) -> None:
        response = api_client.post("/api/v1/videos/ingest", json={"urls": []})
        assert response.status_code == 422


class TestSearchAPI:
    def test_search_success(self, api_client: TestClient) -> None:
        api_client.mock_search.search.return_value = SearchResponse(
            query="protein",
            results=[
                SearchResultItem(
                    video_id="vid1",
                    title="Title",
                    channel="Channel",
                    thumbnail="https://img.example/t.jpg",
                    url="https://www.youtube.com/watch?v=vid1",
                    original_url="https://www.youtube.com/watch?v=vid1",
                    timestamp_url="https://www.youtube.com/watch?v=vid1&t=12",
                    matched_text="protein meals",
                    start_time=12.0,
                    relevance_score=0.85,
                    why_matched="Transcript passage matched (at 12s): \"protein meals\" Relevance score: 0.85.",
                    one_line_memory="Title — protein-focused meals.",
                    why_saved=["You saved content from Channel."],
                    action_items=["Try meal prep on Sunday."],
                )
            ],
        )
        response = api_client.get("/api/v1/search", params={"q": "protein", "limit": 5})
        assert response.status_code == 200
        body = response.json()["results"][0]
        assert body["video_id"] == "vid1"
        assert body["one_line_memory"]
        assert body["why_saved"]
        assert body["action_items"]
        assert body["timestamp_url"]
        assert body["original_url"]

    def test_search_rejects_empty_query(self, api_client: TestClient) -> None:
        response = api_client.get("/api/v1/search", params={"q": "   "})
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_search_validates_limit(self, api_client: TestClient) -> None:
        response = api_client.get("/api/v1/search", params={"q": "test", "limit": 0})
        assert response.status_code == 422

        response = api_client.get("/api/v1/search", params={"q": "test", "limit": 21})
        assert response.status_code == 422

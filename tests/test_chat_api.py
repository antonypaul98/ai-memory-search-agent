"""Tests for chat API validation and responses."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings, get_chat_service
from app.config import Settings, get_settings
from app.models.chat import ChatResponse, ChatSource
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.services.chat_service import ChatService


def _demo_user() -> UserPublic:
    return UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Local Demo User")


@pytest.fixture
def chat_api_client(test_settings: Settings) -> TestClient:
    from app.main import app

    mock_chat = MagicMock(spec=ChatService)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = _demo_user
    app.dependency_overrides[get_chat_service] = lambda: mock_chat

    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as client:
            client.mock_chat = mock_chat
            yield client

    app.dependency_overrides.clear()


class TestChatAPI:
    def test_chat_success(self, chat_api_client: TestClient) -> None:
        chat_api_client.mock_chat.chat.return_value = ChatResponse(
            answer="Based on your saved memories:\n- Install the GPU driver first.",
            grounded=True,
            sources=[
                ChatSource(
                    video_id="vid1",
                    title="GPU Setup",
                    url="https://www.youtube.com/watch?v=vid1",
                    start_time=762.0,
                    end_time=810.0,
                    matched_text="Install the GPU driver first.",
                    relevance_score=0.82,
                    timestamp_url="https://www.youtube.com/watch?v=vid1&t=762",
                )
            ],
        )
        response = chat_api_client.post(
            "/api/v1/chat",
            json={"question": "How do I install the GPU?", "top_k": 6},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["grounded"] is True
        assert body["sources"][0]["timestamp_url"].endswith("t=762")

    def test_chat_rejects_empty_question(self, chat_api_client: TestClient) -> None:
        response = chat_api_client.post("/api/v1/chat", json={"question": "   ", "top_k": 6})
        assert response.status_code == 422

    def test_chat_validates_top_k(self, chat_api_client: TestClient) -> None:
        response = chat_api_client.post(
            "/api/v1/chat",
            json={"question": "What is protein?", "top_k": 0},
        )
        assert response.status_code == 422

        response = chat_api_client.post(
            "/api/v1/chat",
            json={"question": "What is protein?", "top_k": 11},
        )
        assert response.status_code == 422

"""Regression coverage for privacy-safe F-34 core domain events."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dependencies import get_chat_service, get_search_service
from app.main import app
from app.models.chat import ChatResponse
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SearchResponse
from app.services.event_bus import EventBus


class _SearchStub:
    def search(self, **_kwargs) -> SearchResponse:
        return SearchResponse(
            query="private search terms",
            results=[],
            filters_applied={"channel": "private-channel"},
        )


class _ChatStub:
    def chat(self, **_kwargs) -> ChatResponse:
        return ChatResponse(
            answer="private generated answer",
            sources=[],
            grounded=False,
            needs_clarification=True,
            clarification_prompt="private clarification",
        )


def test_search_emits_request_correlated_event_without_query_text(
    client: TestClient, test_settings
) -> None:
    app.dependency_overrides[get_search_service] = lambda: _SearchStub()

    response = client.get(
        "/api/v1/search",
        params={"q": "private search terms", "channel": "private-channel"},
        headers={"X-Request-ID": "search-trace-1"},
    )
    assert response.status_code == 200

    events, _ = EventBus(test_settings).list_events(
        user_id=LOCAL_DEFAULT_USER_ID,
        event_type="search.completed",
    )
    assert len(events) == 1
    event = events[0]
    assert event.request_id == "search-trace-1"
    assert event.actor == "user"
    assert event.payload == {
        "filters_applied": True,
        "limit": 5,
        "result_count": 0,
    }
    persisted = str(event.payload)
    assert "private search terms" not in persisted
    assert "private-channel" not in persisted


def test_chat_emits_grounding_metadata_without_question_or_answer_text(
    client: TestClient, test_settings
) -> None:
    app.dependency_overrides[get_chat_service] = lambda: _ChatStub()

    response = client.post(
        "/api/v1/chat",
        json={"question": "private interview question", "top_k": 4},
        headers={"X-Request-ID": "chat-trace-1"},
    )
    assert response.status_code == 200

    events, _ = EventBus(test_settings).list_events(
        user_id=LOCAL_DEFAULT_USER_ID,
        event_type="chat.completed",
    )
    assert len(events) == 1
    event = events[0]
    assert event.request_id == "chat-trace-1"
    assert event.actor == "user"
    assert event.payload == {
        "grounded": False,
        "needs_clarification": True,
        "source_count": 0,
    }
    persisted = str(event.payload)
    assert "private interview question" not in persisted
    assert "private generated answer" not in persisted
    assert "private clarification" not in persisted

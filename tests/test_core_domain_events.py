"""Regression coverage for privacy-safe F-34 core domain events."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dependencies import get_chat_service, get_search_service
from app.db.job_store import JobStore
from app.main import app
from app.models.chat import ChatResponse
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SearchResponse
from app.services.event_bus import EventBus
from app.services.playlist_service import PlaylistVideoEntry


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


def test_job_lifecycle_events_are_correlated_and_exclude_private_job_content(
    client: TestClient, test_settings
) -> None:
    private_url = "https://www.youtube.com/watch?v=private123"
    private_title = "private playlist item title"
    private_playlist_title = "private playlist title"
    job = JobStore(test_settings).create_playlist_job(
        user_id=LOCAL_DEFAULT_USER_ID,
        playlist_id="PL-private",
        playlist_title=private_playlist_title,
        entries=[
            PlaylistVideoEntry(
                video_id="private123",
                url=private_url,
                title=private_title,
            )
        ],
        reflection=None,
        force_refresh=False,
    )

    pause = client.post(
        f"/api/v1/jobs/{job.job_id}/pause",
        headers={"X-Request-ID": "job-pause-trace"},
    )
    assert pause.status_code == 200

    delete = client.delete(
        f"/api/v1/jobs/{job.job_id}",
        headers={"X-Request-ID": "job-delete-trace"},
    )
    assert delete.status_code == 200

    events, _ = EventBus(test_settings).list_events(
        user_id=LOCAL_DEFAULT_USER_ID,
        event_type="job.state_changed",
    )
    assert len(events) == 2

    paused_event, deleted_event = events
    assert paused_event.aggregate_type == "job"
    assert paused_event.aggregate_id == job.job_id
    assert paused_event.request_id == "job-pause-trace"
    assert paused_event.actor == "user"
    assert paused_event.payload == {
        "action": "pause",
        "status": "queued",
        "paused": True,
        "queued": 1,
        "processing": 0,
        "completed": 0,
        "skipped": 0,
        "failed": 0,
        "total_videos": 1,
    }
    assert deleted_event.aggregate_id == job.job_id
    assert deleted_event.request_id == "job-delete-trace"
    assert deleted_event.payload == {"action": "delete"}

    persisted = " ".join(str(event.payload) for event in events)
    assert private_url not in persisted
    assert private_title not in persisted
    assert private_playlist_title not in persisted

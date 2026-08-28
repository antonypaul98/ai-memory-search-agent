"""Phase 4 F-34 event-bus foundation regression tests."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.event_bus import EventBus


def test_emit_persists_and_lists_tenant_scoped(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    mine = bus.emit(
        user_id="user-a",
        event_type="memory.ingested",
        aggregate_type="memory",
        aggregate_id="mem-1",
        payload={"source_type": "web"},
    )
    bus.emit(user_id="user-b", event_type="memory.ingested", aggregate_id="mem-2")

    events, cursor = bus.list_events(user_id="user-a")
    assert [event.event_id for event in events] == [mine.event_id]
    assert events[0].aggregate_id == "mem-1"
    assert events[0].payload == {"source_type": "web"}
    assert cursor is not None


def test_event_type_filter_and_cursor(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    bus.emit(user_id="u1", event_type="search.completed")
    bus.emit(user_id="u1", event_type="chat.completed")
    bus.emit(user_id="u1", event_type="search.completed")

    first, cursor = bus.list_events(user_id="u1", event_type="search.completed", limit=1)
    assert len(first) == 1
    assert cursor is not None
    rest, _ = bus.list_events(
        user_id="u1", event_type="search.completed", after_id=cursor, limit=10
    )
    assert len(rest) == 1
    assert rest[0].event_type == "search.completed"


def test_request_id_provides_tenant_scoped_trace_filter(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    bus.emit(user_id="u1", event_type="capture.started", request_id="trace-1")
    bus.emit(user_id="u1", event_type="capture.completed", request_id="trace-1")
    bus.emit(user_id="u1", event_type="capture.completed", request_id="trace-2")
    bus.emit(user_id="u2", event_type="capture.completed", request_id="trace-1")

    events, _ = bus.list_events(user_id="u1", request_id="trace-1")
    assert [event.event_type for event in events] == ["capture.started", "capture.completed"]
    assert all(event.user_id == "u1" for event in events)


def test_subscribers_receive_persisted_event_and_fail_open(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    seen: list[str] = []

    def broken(_event) -> None:
        raise RuntimeError("subscriber boom")

    bus.subscribe("*", broken)
    bus.subscribe("memory.updated", lambda event: seen.append(event.event_id))
    event = bus.emit(user_id="u1", event_type="memory.updated")

    assert seen == [event.event_id]
    persisted, _ = bus.list_events(user_id="u1")
    assert [item.event_id for item in persisted] == [event.event_id]


def test_emit_rejects_invalid_or_unserializable_input(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    with pytest.raises(ValueError, match="user_id"):
        bus.emit(user_id="", event_type="memory.updated")
    with pytest.raises(ValueError, match="event_type"):
        bus.emit(user_id="u1", event_type="")
    with pytest.raises(ValueError, match="JSON serializable"):
        bus.emit(user_id="u1", event_type="memory.updated", payload={"bad": object()})


def test_event_payload_redacts_credentials_recursively(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    event = bus.emit(
        user_id="u1",
        event_type="connector.connected",
        payload={
            "access_token": "top-secret",
            "nested": {"api_key": "also-secret", "safe": "provider"},
        },
    )
    assert event.payload == {
        "access_token": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "safe": "provider"},
    }
    persisted, _ = bus.list_events(user_id="u1")
    assert "top-secret" not in str(persisted[0].payload)
    assert "also-secret" not in str(persisted[0].payload)


def test_metrics_are_durable_and_tenant_scoped(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    bus.emit(user_id="u1", event_type="search.completed")
    bus.emit(user_id="u1", event_type="search.completed")
    bus.emit(user_id="u1", event_type="chat.completed")
    bus.emit(user_id="u2", event_type="search.completed")

    assert bus.metrics(user_id="u1") == {"chat.completed": 1, "search.completed": 2}
    assert EventBus(test_settings).metrics(user_id="u1") == {
        "chat.completed": 1,
        "search.completed": 2,
    }


def test_table_is_idempotent_and_audit_rows_are_append_only(test_settings: Settings) -> None:
    EventBus(test_settings)
    bus = EventBus(test_settings)
    bus.emit(user_id="u1", event_type="memory.created")
    bus.emit(user_id="u1", event_type="memory.created")

    with sqlite3.connect(test_settings.sqlite_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0]
    assert count == 2


def test_events_api_returns_only_current_user(
    client: TestClient, test_settings: Settings
) -> None:
    bus = EventBus(test_settings)
    bus.emit(
        user_id=LOCAL_DEFAULT_USER_ID,
        event_type="memory.ingested",
        aggregate_id="mine",
    )
    bus.emit(user_id="someone-else", event_type="memory.ingested", aggregate_id="theirs")

    response = client.get("/api/v1/events")
    assert response.status_code == 200
    data = response.json()
    assert [event["aggregate_id"] for event in data["events"]] == ["mine"]
    assert all(event["user_id"] == LOCAL_DEFAULT_USER_ID for event in data["events"])


def test_events_api_supports_trace_filter_and_metrics(
    client: TestClient, test_settings: Settings
) -> None:
    bus = EventBus(test_settings)
    bus.emit(
        user_id=LOCAL_DEFAULT_USER_ID,
        event_type="search.completed",
        request_id="req-a",
    )
    bus.emit(
        user_id=LOCAL_DEFAULT_USER_ID,
        event_type="chat.completed",
        request_id="req-b",
    )
    bus.emit(user_id="someone-else", event_type="search.completed", request_id="req-a")

    traced = client.get("/api/v1/events?request_id=req-a")
    assert traced.status_code == 200
    assert [item["event_type"] for item in traced.json()["events"]] == ["search.completed"]

    metrics = client.get("/api/v1/events/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["counts"] == {"chat.completed": 1, "search.completed": 1}


def test_events_api_validates_limit(client: TestClient) -> None:
    response = client.get("/api/v1/events?limit=501")
    assert response.status_code == 422

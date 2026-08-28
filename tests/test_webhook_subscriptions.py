"""F-34 durable webhook subscription regression tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.exceptions import AppError
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.event_bus import EventBus


class _Response:
    def raise_for_status(self) -> None:
        return None


class _RecordingClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
        assert timeout == 5.0
        assert follow_redirects is False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _Response()


def _allow_public(url: str, *, resolve_dns: bool = True) -> str:
    assert url.startswith("https://")
    return url


def test_subscription_registry_is_durable_and_tenant_scoped(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.event_bus.validate_public_http_url", _allow_public)
    bus = EventBus(test_settings)
    mine = bus.create_webhook_subscription(
        user_id="user-a", url="https://hooks.example/a", event_type="search.completed"
    )
    bus.create_webhook_subscription(user_id="user-b", url="https://hooks.example/b")

    listed = EventBus(test_settings).list_webhook_subscriptions(user_id="user-a")
    assert [item.subscription_id for item in listed] == [mine.subscription_id]
    assert str(listed[0].url).startswith("https://hooks.example/a")
    assert listed[0].event_type == "search.completed"

    assert bus.delete_webhook_subscription(
        user_id="user-b", subscription_id=mine.subscription_id
    ) is False
    assert bus.delete_webhook_subscription(
        user_id="user-a", subscription_id=mine.subscription_id
    ) is True
    assert bus.list_webhook_subscriptions(user_id="user-a") == []


def test_delivery_filters_event_type_and_omits_tenant_identifier(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _RecordingClient.calls = []
    monkeypatch.setattr("app.services.event_bus.validate_public_http_url", _allow_public)
    monkeypatch.setattr("app.services.event_bus.httpx.Client", _RecordingClient)
    bus = EventBus(test_settings)
    bus.create_webhook_subscription(
        user_id="u1", url="https://hooks.example/search", event_type="search.completed"
    )
    bus.create_webhook_subscription(user_id="u1", url="https://hooks.example/all")
    bus.create_webhook_subscription(user_id="u2", url="https://hooks.example/other")

    bus.emit(
        user_id="u1",
        event_type="search.completed",
        aggregate_type="search",
        aggregate_id="search-1",
        payload={"result_count": 2},
    )

    assert [call["url"] for call in _RecordingClient.calls] == [
        "https://hooks.example/search",
        "https://hooks.example/all",
    ]
    for call in _RecordingClient.calls:
        assert "user_id" not in call["json"]
        assert call["json"]["event_type"] == "search.completed"
        assert call["json"]["payload"] == {"result_count": 2}


def test_delivery_keeps_event_redaction_and_does_not_follow_redirects(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _RecordingClient.calls = []
    monkeypatch.setattr("app.services.event_bus.validate_public_http_url", _allow_public)
    monkeypatch.setattr("app.services.event_bus.httpx.Client", _RecordingClient)
    bus = EventBus(test_settings)
    bus.create_webhook_subscription(user_id="u1", url="https://hooks.example/all")

    bus.emit(
        user_id="u1",
        event_type="connector.connected",
        payload={"api_key": "do-not-send", "provider": "example"},
    )

    assert len(_RecordingClient.calls) == 1
    sent = _RecordingClient.calls[0]["json"]
    assert sent["payload"] == {"api_key": "[REDACTED]", "provider": "example"}
    assert "do-not-send" not in str(sent)


def test_delivery_failure_never_rolls_back_committed_event(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.event_bus.validate_public_http_url", _allow_public)
    bus = EventBus(test_settings)
    bus.create_webhook_subscription(user_id="u1", url="https://hooks.example/all")

    def blocked(_url: str, *, resolve_dns: bool = True) -> str:
        raise AppError("destination became unsafe")

    monkeypatch.setattr("app.services.event_bus.validate_public_http_url", blocked)
    event = bus.emit(user_id="u1", event_type="memory.updated")

    persisted, _ = bus.list_events(user_id="u1")
    assert [item.event_id for item in persisted] == [event.event_id]


def test_webhook_api_requires_confirmation_and_rejects_private_target(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfirmed = client.post(
        "/api/v1/events/webhooks",
        json={"url": "https://hooks.example/events", "event_type": "*"},
    )
    assert unconfirmed.status_code == 409

    private = client.post(
        "/api/v1/events/webhooks",
        json={"url": "http://127.0.0.1/hook", "event_type": "*", "confirmed": True},
    )
    assert private.status_code == 400


def test_webhook_api_create_list_delete(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.event_bus.validate_public_http_url", _allow_public)
    created = client.post(
        "/api/v1/events/webhooks",
        json={
            "url": "https://hooks.example/events",
            "event_type": "chat.completed",
            "confirmed": True,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["event_type"] == "chat.completed"
    subscription_id = body["subscription_id"]

    listed = client.get("/api/v1/events/webhooks")
    assert listed.status_code == 200
    assert [item["subscription_id"] for item in listed.json()["subscriptions"]] == [
        subscription_id
    ]

    deleted = client.delete(f"/api/v1/events/webhooks/{subscription_id}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/events/webhooks").json()["subscriptions"] == []

    missing = client.delete(f"/api/v1/events/webhooks/{subscription_id}")
    assert missing.status_code == 404


def test_subscription_creation_rejects_localhost_without_dns(test_settings: Settings) -> None:
    bus = EventBus(test_settings)
    with pytest.raises(AppError):
        bus.create_webhook_subscription(
            user_id=LOCAL_DEFAULT_USER_ID,
            url="http://localhost/internal",
        )

"""Selected EventBus persistence: real Postgres, exact tenant scope, no SQLite fallback."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError, get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.services.event_bus import EventBus


def test_selected_event_bus_missing_dsn_never_opens_sqlite(monkeypatch, tmp_path):
    env_name = "P03_EVENT_BUS_MISSING_DSN"
    monkeypatch.delenv(env_name, raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres EventBus opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    settings = Settings(
        _env_file=None,
        memory_store_backend="postgres",
        postgres_dsn_env=env_name,
        sqlite_path=str(tmp_path / "forbidden.db"),
    )
    with pytest.raises(PostgresConfigurationError):
        EventBus(settings)
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()


@pytest.fixture
def pg_event_bus(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres EventBus opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    nonce = uuid4().hex
    owner, other = f"event-owner-{nonce}", f"event-other-{nonce}"
    bus = EventBus(settings)
    factory = get_postgres_connection_factory(settings)
    try:
        yield settings, bus, factory, owner, other
    finally:
        with factory() as conn:
            conn.execute(
                "DELETE FROM webhook_subscriptions WHERE user_id IN (%s, %s)",
                (owner, other),
            )
            conn.execute(
                "DELETE FROM memory_events WHERE user_id IN (%s, %s)",
                (owner, other),
            )
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_postgres_event_audit_round_trip_is_tenant_scoped_and_redacted(pg_event_bus):
    settings, bus, _, owner, other = pg_event_bus
    emitted = bus.emit(
        user_id=owner,
        event_type="memory.created",
        aggregate_type="memory",
        aggregate_id="m-1",
        actor="acceptance-test",
        request_id="req-1",
        payload={"label": "safe", "access_token": "must-not-persist"},
    )
    assert emitted.payload == {"label": "safe", "access_token": "[REDACTED]"}

    restarted = EventBus(settings)
    events, cursor = restarted.list_events(user_id=owner, request_id="req-1")
    assert [event.event_id for event in events] == [emitted.event_id]
    assert events[0].payload["access_token"] == "[REDACTED]"
    assert isinstance(cursor, int)
    assert restarted.metrics(user_id=owner) == {"memory.created": 1}

    other_events, other_cursor = restarted.list_events(user_id=other)
    assert other_events == []
    assert other_cursor is None
    assert restarted.metrics(user_id=other) == {}


def test_postgres_webhook_subscription_crud_is_exact_tenant(pg_event_bus):
    settings, bus, _, owner, other = pg_event_bus
    subscription = bus.create_webhook_subscription(
        user_id=owner,
        event_type="memory.deleted",
        url="https://example.com/hook",
    )
    restarted = EventBus(settings)
    owner_rows = restarted.list_webhook_subscriptions(user_id=owner)
    assert [row.subscription_id for row in owner_rows] == [subscription.subscription_id]
    assert restarted.list_webhook_subscriptions(user_id=other) == []
    assert restarted.delete_webhook_subscription(
        user_id=other, subscription_id=subscription.subscription_id
    ) is False
    assert restarted.list_webhook_subscriptions(user_id=owner)
    assert restarted.delete_webhook_subscription(
        user_id=owner, subscription_id=subscription.subscription_id
    ) is True
    assert restarted.list_webhook_subscriptions(user_id=owner) == []

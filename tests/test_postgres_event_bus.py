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


@pytest.mark.parametrize("owner", ["", "   ", None])
def test_event_privacy_rejects_missing_owner_before_sql(owner):
    from app.db.postgres_event_store import PostgresEventStore

    store = PostgresEventStore.__new__(PostgresEventStore)
    def forbidden_connection():
        raise AssertionError("invalid owner reached SQL")
    store._connection_factory = forbidden_connection
    with pytest.raises(ValueError, match="user_id is required"):
        store.export_user_data(user_id=owner)
    with pytest.raises(ValueError, match="user_id is required"):
        store.delete_user_data(user_id=owner)


def test_event_privacy_export_is_complete_redacted_and_retry_safe(pg_event_bus):
    import json
    import psycopg
    from psycopg import sql

    _, bus, factory, owner, other = pg_event_bus
    store = bus._postgres
    assert store is not None
    for user_id in (owner, other):
        store.create_subscription(subscription_id=uuid4().hex, user_id=user_id,
                                  event_type="*", url="https://example.test/hook?secret=fixture-secret",
                                  created_at="2026-01-01T00:00:00Z")
    # Exceed the interactive page size; include legacy payloads to verify export redaction.
    with factory() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO memory_events(event_id, user_id, event_type, payload_json, created_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                [(uuid4().hex, user_id, "privacy.fixture",
                  json.dumps({"nested": [{"access_token": "fixture-secret", "count": i}]}),
                  "2026-01-01T00:00:00Z")
                 for user_id in (owner, other) for i in range(105)],
            )
    exported = bus.export_user_data(user_id=owner)
    neighbor = bus.export_user_data(user_id=other)
    assert len(exported["events"]) == 105
    assert [row["id"] for row in exported["events"]] == sorted(row["id"] for row in exported["events"])
    assert all(row["user_id"] == owner for row in exported["events"])
    assert all(row["user_id"] == owner for row in exported["subscriptions"])
    assert all("url" not in row for row in exported["subscriptions"])
    assert "fixture-secret" not in json.dumps(exported)
    assert exported["events"][0]["payload"]["nested"][0]["access_token"] == "[REDACTED]"

    trigger = "privacy_event_failure_" + uuid4().hex
    with factory() as conn:
        conn.execute(sql.SQL("""CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF OLD.user_id = {} THEN RAISE EXCEPTION 'injected event deletion failure';
            END IF; RETURN OLD; END $$""").format(sql.Identifier(trigger), sql.Literal(owner)))
        conn.execute(sql.SQL("CREATE TRIGGER {} BEFORE DELETE ON memory_events FOR EACH ROW EXECUTE FUNCTION {}()")
                     .format(sql.Identifier(trigger), sql.Identifier(trigger)))
    try:
        with pytest.raises(psycopg.Error, match="injected event deletion failure"):
            store.delete_user_data(user_id=owner)
        # Subscription deletion happened first, but must roll back with the event failure.
        assert bus.export_user_data(user_id=owner) == exported
        assert bus.export_user_data(user_id=other) == neighbor
    finally:
        with factory() as conn:
            conn.execute(sql.SQL("DROP TRIGGER {} ON memory_events").format(sql.Identifier(trigger)))
            conn.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(trigger)))
    assert store.delete_user_data(user_id=owner) == {"events": 105, "subscriptions": 1}
    assert store.delete_user_data(user_id=owner) == {"events": 0, "subscriptions": 0}
    assert bus.export_user_data(user_id=owner) == {"events": [], "subscriptions": []}
    assert bus.export_user_data(user_id=other) == neighbor

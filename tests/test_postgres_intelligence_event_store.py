from __future__ import annotations

from datetime import date

import pytest

from app.config import Settings
from app.db import intelligence_event_store_factory
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_intelligence_event_store import PostgresIntelligenceEventStore
from app.db.postgres_runtime import PostgresConfigurationError


def test_intelligence_event_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "events.db"))
    store = intelligence_event_store_factory.get_intelligence_event_store(settings)
    assert isinstance(store, IntelligenceStore)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_intelligence_event_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_INTELLIGENCE_EVENT_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)
    with pytest.raises(PostgresConfigurationError):
        intelligence_event_store_factory.get_intelligence_event_store(settings)


def test_intelligence_event_schema_is_tenant_indexed_and_deterministic():
    statements: list[tuple[str, tuple | None]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return self

    PostgresIntelligenceEventStore(lambda: FakeConnection())
    sql = "\n".join(statement for statement, _ in statements)
    assert "id BIGSERIAL PRIMARY KEY" in sql
    assert "idx_intel_events_user_created ON intelligence_events(user_id, created_at DESC, id DESC)" in sql
    assert "idx_intel_events_type ON intelligence_events(user_id, event_type, created_at DESC, id DESC)" in sql


def test_event_reads_are_exact_tenant_and_deterministic():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return FakeResult()

    store = PostgresIntelligenceEventStore(lambda: FakeConnection())
    statements.clear()

    assert store.recent_events("tenant-a", limit=17) == []
    query, params = statements[-1]
    assert "WHERE user_id = %s" in query
    assert "ORDER BY created_at DESC, id DESC LIMIT %s" in query
    assert params == ("tenant-a", 17)

    assert store.recent_events("tenant-a", event_type="search", limit=9) == []
    query, params = statements[-1]
    assert "WHERE user_id = %s AND event_type = %s" in query
    assert params == ("tenant-a", "search", 9)


def test_record_event_requires_identity_and_writes_exact_tenant():
    statements: list[tuple[str, tuple | None]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return self

    store = PostgresIntelligenceEventStore(lambda: FakeConnection())
    statements.clear()

    with pytest.raises(ValueError):
        store.record_event(user_id="", event_type="save")
    with pytest.raises(ValueError):
        store.record_event(user_id="tenant-a", event_type="")

    store.record_event(user_id="tenant-a", event_type="save", topic="python", video_id="v1")
    query, params = statements[-1]
    assert "INSERT INTO intelligence_events" in query
    assert params[0:5] == ("tenant-a", "save", "python", "v1", None)


def test_save_dates_are_utc_scoped_to_save_events():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchall(self):
            return [{"d": date(2026, 9, 12)}, {"d": date(2026, 9, 10)}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return FakeResult()

    store = PostgresIntelligenceEventStore(lambda: FakeConnection())
    statements.clear()

    assert store.save_dates("tenant-a") == ["2026-09-12", "2026-09-10"]
    query, params = statements[-1]
    assert "user_id = %s AND event_type = 'save'" in query
    assert "AT TIME ZONE 'UTC'" in query
    assert params == ("tenant-a",)

from __future__ import annotations

import pytest

from app.config import Settings
from app.db import topic_store_factory
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_runtime import PostgresConfigurationError
from app.db.postgres_topic_store import PostgresTopicStore


def test_topic_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "topics.db"))

    store = topic_store_factory.get_topic_store(settings)

    assert isinstance(store, IntelligenceStore)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_topic_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_TOPIC_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        topic_store_factory.get_topic_store(settings)


def test_postgres_selection_uses_environment_owned_connection_factory(monkeypatch):
    connection_factory = object()
    calls: list[object] = []

    class FakePostgresTopicStore:
        def __init__(self, resolved_factory):
            calls.append(resolved_factory)

    monkeypatch.setattr(
        topic_store_factory,
        "get_postgres_connection_factory",
        lambda settings: connection_factory,
    )
    monkeypatch.setattr(topic_store_factory, "PostgresTopicStore", FakePostgresTopicStore)

    store = topic_store_factory.get_topic_store(Settings(memory_store_backend="postgres"))

    assert isinstance(store, FakePostgresTopicStore)
    assert calls == [connection_factory]


def test_postgres_topic_schema_preserves_tenant_identity_and_relationships():
    statements: list[tuple[str, tuple | None]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return self

    PostgresTopicStore(lambda: FakeConnection())

    sql = "\n".join(statement for statement, _ in statements)
    assert "UNIQUE(user_id, normalized_name)" in sql
    assert "PRIMARY KEY(topic_id, video_id)" in sql
    assert "topic_id TEXT NOT NULL REFERENCES topic_profiles(topic_id) ON DELETE CASCADE" in sql
    assert "idx_topic_links_tenant_video ON topic_memory_links(user_id, video_id, topic_id)" in sql


def test_topic_export_is_exact_tenant_bounded_and_deterministic():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchall(self):
            return [
                {
                    "topic_id": "topic-1",
                    "user_id": "tenant-a",
                    "name": "Postgres",
                    "normalized_name": "postgres",
                }
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            normalized = " ".join(str(statement).split())
            statements.append((normalized, params))
            if normalized.startswith("SELECT * FROM topic_profiles"):
                return FakeResult()
            return self

    store = PostgresTopicStore(lambda: FakeConnection())
    statements.clear()

    rows = store.list_for_export(user_id="tenant-a", limit=321)

    assert rows[0]["user_id"] == "tenant-a"
    query, params = statements[-1]
    assert "WHERE user_id = %s" in query
    assert "ORDER BY last_updated_at DESC, topic_id ASC" in query
    assert "LIMIT %s" in query
    assert params == ("tenant-a", 321)

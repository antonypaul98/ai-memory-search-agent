from __future__ import annotations

import pytest

from app.config import Settings
from app.db import learning_edge_store_factory
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_learning_edge_store import PostgresLearningEdgeStore
from app.db.postgres_runtime import PostgresConfigurationError
from app.models.intelligence import LearningRelation


def test_learning_edge_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "edges.db"))

    store = learning_edge_store_factory.get_learning_edge_store(settings)

    assert isinstance(store, IntelligenceStore)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_learning_edge_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_EDGE_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        learning_edge_store_factory.get_learning_edge_store(settings)


def test_postgres_learning_edge_schema_preserves_tenant_identity_and_natural_key():
    statements: list[tuple[str, tuple | None]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return self

    PostgresLearningEdgeStore(lambda: FakeConnection())

    sql = "\n".join(statement for statement, _ in statements)
    assert "UNIQUE(user_id, source_video_id, target_video_id, relation)" in sql
    assert "idx_learning_edges_source ON learning_edges(user_id, source_video_id" in sql
    assert "idx_learning_edges_target ON learning_edges(user_id, target_video_id" in sql


def test_learning_edge_reads_are_exact_tenant_and_deterministic():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchall(self):
            return []

        def fetchone(self):
            return {"c": 0}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return FakeResult()

    store = PostgresLearningEdgeStore(lambda: FakeConnection())
    statements.clear()

    assert store.edges_for_video("video-1", user_id="tenant-a", limit=17) == []
    query, params = statements[-1]
    assert "WHERE user_id = %s" in query
    assert "ORDER BY strength DESC, edge_id ASC LIMIT %s" in query
    assert params == ("tenant-a", "video-1", "video-1", 17)

    assert store.edges_for_topic_videos(["a", "b"], user_id="tenant-a", limit=23) == []
    query, params = statements[-1]
    assert "WHERE user_id = %s" in query
    assert "source_video_id = ANY(%s)" in query
    assert "target_video_id = ANY(%s)" in query
    assert params == ("tenant-a", ["a", "b"], ["a", "b"], 23)

    assert store.count_edges("tenant-a") == 0
    query, params = statements[-1]
    assert "WHERE user_id = %s" in query
    assert params == ("tenant-a",)


def test_learning_edge_upsert_rejects_self_edge_before_connecting():
    calls = 0

    def connection_factory():
        nonlocal calls
        calls += 1
        raise AssertionError("should not connect")

    store = object.__new__(PostgresLearningEdgeStore)
    store._connection_factory = connection_factory

    with pytest.raises(ValueError, match="self-edge"):
        store.upsert_edge(
            user_id="tenant-a",
            source_video_id="same",
            target_video_id="same",
            relation=LearningRelation.SAME_TOPIC,
            strength=0.5,
            evidence="evidence",
        )

    assert calls == 0

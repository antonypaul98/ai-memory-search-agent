from __future__ import annotations

import pytest

from app.config import Settings
from app.db import concept_capsule_store_factory
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_concept_capsule_store import PostgresConceptCapsuleStore
from app.db.postgres_runtime import PostgresConfigurationError


def test_concept_capsule_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "capsules.db"))

    store = concept_capsule_store_factory.get_concept_capsule_store(settings)

    assert isinstance(store, IntelligenceStore)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_concept_capsule_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_CONCEPT_CAPSULE_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        concept_capsule_store_factory.get_concept_capsule_store(settings)


def test_postgres_concept_capsule_schema_preserves_tenant_identity():
    statements: list[tuple[str, tuple | None]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return self

    PostgresConceptCapsuleStore(lambda: FakeConnection())

    sql = "\n".join(statement for statement, _ in statements)
    assert "UNIQUE(user_id, normalized_name)" in sql
    assert "idx_concept_capsules_user_order ON concept_capsules(user_id" in sql


def test_concept_capsule_reads_are_exact_tenant_and_deterministic():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchall(self):
            return []

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return FakeResult()

    store = PostgresConceptCapsuleStore(lambda: FakeConnection())
    statements.clear()

    assert store.get_concept_capsule("ccap-1", user_id="tenant-a") is None
    query, params = statements[-1]
    assert "capsule_id = %s AND user_id = %s" in query
    assert params == ("ccap-1", "tenant-a")

    assert store.list_concept_capsules("tenant-a", limit=17) == []
    query, params = statements[-1]
    assert "WHERE user_id = %s" in query
    assert "ORDER BY progress_total DESC, updated_at DESC, capsule_id ASC" in query
    assert params == ("tenant-a", 17)


def test_concept_capsule_upsert_rejects_empty_name_before_connecting():
    calls = 0

    def connection_factory():
        nonlocal calls
        calls += 1
        raise AssertionError("should not connect")

    store = object.__new__(PostgresConceptCapsuleStore)
    store._connection_factory = connection_factory

    with pytest.raises(ValueError, match="empty concept capsule name"):
        store.upsert_concept_capsule(
            user_id="tenant-a",
            name="!!!",
            summary="summary",
            topic_ids=[],
            video_ids=[],
            creators=[],
        )

    assert calls == 0


def test_concept_capsule_upsert_caps_progress_and_preserves_tenant_key():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchone(self):
            return {
                "capsule_id": "ccap-existing",
                "user_id": "tenant-a",
                "name": "Python",
                "normalized_name": "python",
                "summary": "summary",
                "topic_ids_json": '["topic-1"]',
                "memory_video_ids_json": '["video-1", "video-2"]',
                "creator_names_json": '["creator"]',
                "progress_total": 2,
                "progress_completed": 2,
                "updated_at": "2026-09-12T00:00:00+00:00",
            }

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return FakeResult()

    store = PostgresConceptCapsuleStore(lambda: FakeConnection())
    statements.clear()

    capsule = store.upsert_concept_capsule(
        user_id="tenant-a",
        name=" Python ",
        summary="summary",
        topic_ids=["topic-1"],
        video_ids=["video-1", "video-2"],
        creators=["creator"],
        progress_completed=99,
    )

    query, params = statements[-1]
    assert "ON CONFLICT(user_id, normalized_name) DO UPDATE" in query
    assert params[1] == "tenant-a"
    assert params[3] == "python"
    assert params[8] == 2
    assert params[9] == 2
    assert capsule.capsule_id == "ccap-existing"
    assert capsule.learning_progress == 1.0

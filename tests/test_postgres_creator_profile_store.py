from __future__ import annotations

import pytest

from app.config import Settings
from app.db import creator_profile_store_factory
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_creator_profile_store import PostgresCreatorProfileStore
from app.db.postgres_runtime import PostgresConfigurationError


def test_creator_profile_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "creators.db"))

    store = creator_profile_store_factory.get_creator_profile_store(settings)

    assert isinstance(store, IntelligenceStore)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_creator_profile_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_CREATOR_PROFILE_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        creator_profile_store_factory.get_creator_profile_store(settings)


def test_creator_profile_schema_preserves_tenant_identity_and_deterministic_order():
    statements: list[tuple[str, tuple | None]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return self

    PostgresCreatorProfileStore(lambda: FakeConnection())

    sql = "\n".join(statement for statement, _ in statements)
    assert "UNIQUE(user_id, normalized_name)" in sql
    assert "idx_creator_profiles_user_order ON creator_profiles(user_id" in sql
    assert "creator_id ASC" in sql


def test_creator_profile_reads_are_exact_tenant_and_deterministic():
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

    store = PostgresCreatorProfileStore(lambda: FakeConnection())
    statements.clear()

    assert store.get_creator("creator-1", user_id="tenant-a") is None
    query, params = statements[-1]
    assert "creator_id = %s AND user_id = %s" in query
    assert params == ("creator-1", "tenant-a")

    assert store.find_creator_by_name("Creator One", user_id="tenant-a") is None
    query, params = statements[-1]
    assert "user_id = %s AND normalized_name = %s" in query
    assert params == ("tenant-a", "creator one")

    assert store.list_creators("tenant-a", limit=17) == []
    query, params = statements[-1]
    assert "WHERE user_id = %s" in query
    assert "ORDER BY video_count DESC, helpful_count DESC, creator_id ASC" in query
    assert params == ("tenant-a", 17)


def test_creator_profile_mutations_lock_exact_tenant_identity():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            if "INSERT INTO creator_profiles" in str(statement):
                return InsertResult(params)
            return FakeResult()

    class InsertResult:
        def __init__(self, params):
            self.params = params

        def fetchone(self):
            p = self.params
            return {
                "creator_id": p[0],
                "user_id": p[1],
                "name": p[2],
                "normalized_name": p[3],
                "channel_id": p[4],
                "video_count": p[5],
                "topics_json": p[6],
                "total_duration_sec": p[7],
                "avg_duration_sec": p[8],
                "beginner_count": p[9],
                "advanced_count": p[10],
                "view_count": p[11],
                "helpful_count": p[12],
                "related_creators_json": p[13],
                "updated_at": p[14],
            }

    store = PostgresCreatorProfileStore(lambda: FakeConnection())
    statements.clear()

    creator = store.upsert_creator(
        user_id="tenant-a",
        name=" Creator One ",
        channel_id="channel-1",
        topics=["python", "python", "testing"],
        duration_sec=120,
        beginner=True,
        view_count=4,
        helpful_count=2,
        related_creators=["Creator Two", "Creator Two"],
    )

    lock_query, lock_params = statements[0]
    assert "user_id = %s AND normalized_name = %s FOR UPDATE" in lock_query
    assert lock_params == ("tenant-a", "creator one")
    assert creator.video_count == 1
    assert creator.topics_covered == ["python", "testing"]
    assert creator.beginner_friendliness == 1.0
    assert creator.related_creators == ["Creator Two"]


def test_replace_creator_stats_locks_exact_tenant_identity_before_write():
    statements: list[tuple[str, tuple | None]] = []

    class FakeResult:
        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            if "INSERT INTO creator_profiles" in str(statement):
                return InsertResult(params)
            return FakeResult()

    class InsertResult:
        def __init__(self, params):
            self.params = params

        def fetchone(self):
            p = self.params
            return {
                "creator_id": p[0], "user_id": p[1], "name": p[2],
                "normalized_name": p[3], "channel_id": p[4], "video_count": p[5],
                "topics_json": p[6], "total_duration_sec": p[7],
                "avg_duration_sec": p[8], "beginner_count": p[9],
                "advanced_count": p[10], "view_count": p[11],
                "helpful_count": p[12], "related_creators_json": p[13],
                "updated_at": p[14],
            }

    store = PostgresCreatorProfileStore(lambda: FakeConnection())
    statements.clear()

    creator = store.replace_creator_stats(
        user_id="tenant-a",
        name="Creator One",
        topics=["python"],
        video_count=2,
        total_duration_sec=300,
        beginner_count=1,
        advanced_count=1,
    )

    lock_query, lock_params = statements[0]
    assert "user_id = %s AND normalized_name = %s FOR UPDATE" in lock_query
    assert lock_params == ("tenant-a", "creator one")
    assert creator.video_count == 2
    assert creator.average_depth_sec == 150
    assert creator.beginner_friendliness == 0.5
    assert creator.advanced_coverage == 0.5

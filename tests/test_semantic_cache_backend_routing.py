"""Regression tests for P-03 semantic-cache backend cutover."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError
import app.services.semantic_cache as semantic_cache_module
from app.services.semantic_cache import SemanticCache


class _FakePostgresStore:
    def __init__(self, _connection_factory) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.bumped = 0

    def versions(self) -> tuple[str, str]:
        return "7", "3"

    def get_exact(self, **kwargs):
        row = self.rows.get((kwargs["user_id"], kwargs["cache_key"]))
        if row and row["query_type"] == kwargs["query_type"]:
            return row
        return None

    def active_candidates(self, **kwargs):
        return [
            row for (user_id, _), row in sorted(self.rows.items())
            if user_id == kwargs["user_id"] and row["query_type"] == kwargs["query_type"]
        ]

    def upsert(self, **kwargs) -> None:
        self.rows[(kwargs["user_id"], kwargs["cache_key"])] = dict(kwargs)

    def stats(self, *, user_id: str):
        total = sum(1 for owner, _ in self.rows if owner == user_id)
        return {
            "total": total,
            "active": total,
            "expired": 0,
            "active_by_query_type": {"factual": total} if total else {},
        }

    def invalidate(self, *, user_id: str, query_type: str | None = None) -> int:
        keys = [
            key for key, row in self.rows.items()
            if key[0] == user_id and (query_type is None or row["query_type"] == query_type)
        ]
        for key in keys:
            del self.rows[key]
        return len(keys)

    def bump_index_version(self) -> str:
        self.bumped += 1
        self.rows.clear()
        return str(7 + self.bumped)


def _postgres_settings(tmp_path) -> Settings:
    return Settings(
        sqlite_path=str(tmp_path / "must-not-be-created.db"),
        semantic_cache_enabled=True,
        semantic_cache_store_backend="postgres",
    )


def test_sqlite_remains_default() -> None:
    assert Settings().semantic_cache_store_backend == "sqlite"


def test_postgres_selection_fails_closed_without_dsn(monkeypatch, tmp_path) -> None:
    settings = _postgres_settings(tmp_path)
    monkeypatch.delenv(settings.postgres_dsn_env, raising=False)

    with pytest.raises(PostgresConfigurationError):
        SemanticCache(settings)

    assert not (tmp_path / "must-not-be-created.db").exists()


def test_postgres_routes_reads_writes_stats_invalidation_and_version_bump_without_sqlite(
    monkeypatch, tmp_path
) -> None:
    settings = _postgres_settings(tmp_path)
    fake_store = _FakePostgresStore(object())

    monkeypatch.setattr(semantic_cache_module, "get_postgres_connection_factory", lambda _settings: object())
    monkeypatch.setattr(semantic_cache_module, "PostgresSemanticCacheStore", lambda _factory: fake_store)

    def _sqlite_forbidden(*_args, **_kwargs):
        raise AssertionError("Postgres semantic cache routing touched SQLite")

    monkeypatch.setattr(semantic_cache_module, "migrate", _sqlite_forbidden)
    monkeypatch.setattr(semantic_cache_module, "get_connection", _sqlite_forbidden)
    monkeypatch.setattr(semantic_cache_module, "get_index_version", _sqlite_forbidden)
    monkeypatch.setattr(semantic_cache_module, "get_preference_version", _sqlite_forbidden)
    monkeypatch.setattr(semantic_cache_module, "bump_index_version", _sqlite_forbidden)
    monkeypatch.setattr(semantic_cache_module, "invalidate_semantic_cache", _sqlite_forbidden)

    cache = SemanticCache(settings)
    cache.put(
        question="  Private   Question  ",
        query_embedding=[1.0, 0.0],
        answer={"answer": "tenant-a"},
        query_type="factual",
        user_id="tenant-a",
    )
    cache.put(
        question="Private Question",
        query_embedding=[0.0, 1.0],
        answer={"answer": "tenant-b"},
        query_type="factual",
        user_id="tenant-b",
    )

    exact = cache.get(
        question="private question",
        query_embedding=[1.0, 0.0],
        query_type="factual",
        user_id="tenant-a",
    )
    assert exact == {"answer": {"answer": "tenant-a"}, "cache_type": "exact"}
    assert cache.stats(user_id="tenant-a")["total"] == 1
    assert cache.invalidate(user_id="tenant-b") == 1
    assert cache.stats(user_id="tenant-a")["total"] == 1

    assert cache.bump_index_version_and_invalidate() == "8"
    assert cache.stats(user_id="tenant-a")["total"] == 0
    assert not (tmp_path / "must-not-be-created.db").exists()


def test_postgres_semantic_candidate_is_tenant_scoped(monkeypatch, tmp_path) -> None:
    settings = _postgres_settings(tmp_path).model_copy(
        update={"semantic_cache_similarity_threshold": 0.9}
    )
    fake_store = _FakePostgresStore(object())
    monkeypatch.setattr(semantic_cache_module, "get_postgres_connection_factory", lambda _settings: object())
    monkeypatch.setattr(semantic_cache_module, "PostgresSemanticCacheStore", lambda _factory: fake_store)

    cache = SemanticCache(settings)
    cache.put(
        question="source wording",
        query_embedding=[1.0, 0.0],
        answer={"answer": "allowed"},
        query_type="factual",
        user_id="tenant-a",
    )
    cache.put(
        question="other tenant wording",
        query_embedding=[1.0, 0.0],
        answer={"answer": "private"},
        query_type="factual",
        user_id="tenant-b",
    )

    hit = cache.get(
        question="different wording",
        query_embedding=[1.0, 0.0],
        query_type="factual",
        user_id="tenant-a",
    )
    assert hit and hit["answer"] == {"answer": "allowed"}
    assert hit["cache_type"] == "semantic"

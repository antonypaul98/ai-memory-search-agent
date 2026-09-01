from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.db.postgres_fts_index import PostgresFTSIndex
from app.services.ahme_engine import AdaptiveHierarchicalMemoryEngine
from app.services.fts_index import FTSIndex
from app.services.fts_index_factory import get_fts_index, reset_fts_index_factory_cache


class _Result:
    def fetchall(self):
        return []


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        return _Result()


class _ConnectionFactory:
    def __call__(self):
        return _Connection()


def test_local_sqlite_remains_safe_default(tmp_path):
    reset_fts_index_factory_cache()
    settings = Settings(sqlite_path=str(tmp_path / "fts.db"))

    index = get_fts_index(settings)

    assert isinstance(index, FTSIndex)


def test_authenticated_sqlite_fts_fails_closed(tmp_path):
    reset_fts_index_factory_cache()
    settings = Settings(
        sqlite_path=str(tmp_path / "fts.db"),
        auth_enabled=True,
        fts_store_backend="sqlite",
    )

    with pytest.raises(RuntimeError, match="requires FTS_STORE_BACKEND=postgres"):
        get_fts_index(settings)


def test_postgres_backend_uses_environment_owned_runtime(monkeypatch):
    reset_fts_index_factory_cache()
    factory = _ConnectionFactory()
    settings = Settings(
        fts_store_backend="postgres",
        postgres_dsn_env="PRIVATE_DATABASE_URL",
    )
    calls = []

    def _runtime(resolved_settings):
        calls.append(resolved_settings.postgres_dsn_env)
        return factory

    monkeypatch.setattr(
        "app.services.fts_index_factory.get_postgres_connection_factory",
        _runtime,
    )

    index = get_fts_index(settings)

    assert isinstance(index, PostgresFTSIndex)
    assert calls == ["PRIVATE_DATABASE_URL"]


class _Store:
    def __init__(self):
        self.calls = 0

    def search_level(self, collection, embedding, *, top_k, video_ids=None):
        self.calls += 1
        if self.calls == 1:
            return [{"video_id": "video-a", "doc_id": "capsule_video-a", "relevance_score": 0.9}]
        return []


class _Repository:
    def search(self, *, query_embedding, top_k, user_id):
        return []


class _Cache:
    def get(self, **kwargs):
        return None

    def put(self, **kwargs):
        return None


class _RecordingFTS:
    def __init__(self):
        self.user_ids = []

    def search(self, query, *, limit, video_ids, user_id):
        self.user_ids.append(user_id)
        return []


def test_ahme_forwards_tenant_to_lexical_search(tmp_path):
    settings = Settings(
        sqlite_path=str(tmp_path / "fts.db"),
        hierarchical_retrieval_enabled=True,
        semantic_cache_enabled=False,
    )
    fts = _RecordingFTS()
    engine = AdaptiveHierarchicalMemoryEngine(
        settings=settings,
        repository=_Repository(),
        store=_Store(),
        fts=fts,
        cache=_Cache(),
    )

    with patch("app.services.ahme_engine.embed_query", return_value=[1.0, 0.0]):
        engine.retrieve("protein", user_id="tenant-a", top_k=3)

    assert fts.user_ids == ["tenant-a"]

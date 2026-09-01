from __future__ import annotations

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError
from app.db.sqlite_youtube_memory_store import SQLiteYouTubeMemoryStore
from app.db.youtube_memory_store import YouTubeMemoryStore
from app.db.youtube_memory_store_factory import get_youtube_memory_store


def test_youtube_store_defaults_to_sqlite(tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "memory.db"))

    store = get_youtube_memory_store(settings)

    assert isinstance(store, YouTubeMemoryStore)
    assert isinstance(store, SQLiteYouTubeMemoryStore)


def test_selected_sqlite_store_accepts_tenant_explicit_metrics(monkeypatch, tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "memory.db"))
    calls = []

    def record_metric(_self, key, amount=1.0, *, as_average=False):
        calls.append((key, amount, as_average))

    monkeypatch.setattr(YouTubeMemoryStore, "bump_metric", record_metric)
    store = get_youtube_memory_store(settings)

    store.bump_metric("transcript_success", 1, user_id="tenant-a")
    store.record_search_latency(12.5, user_id="tenant-a")

    assert calls == [
        ("transcript_success", 1, False),
        ("average_search_latency_ms", 12.5, True),
    ]


def test_youtube_store_selects_postgres_as_one_boundary(monkeypatch, tmp_path) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "memory.db"),
        youtube_store_backend="postgres",
    )
    sentinel_factory = lambda: None

    class SentinelPostgresStore:
        def __init__(self, connection_factory) -> None:
            self.connection_factory = connection_factory

    monkeypatch.setattr(
        "app.db.youtube_memory_store_factory.get_postgres_connection_factory",
        lambda selected: sentinel_factory,
    )
    monkeypatch.setattr(
        "app.db.youtube_memory_store_factory.SelectedPostgresYouTubeMemoryStore",
        SentinelPostgresStore,
    )

    store = get_youtube_memory_store(settings)

    assert isinstance(store, SentinelPostgresStore)
    assert store.connection_factory is sentinel_factory
    assert not (tmp_path / "memory.db").exists()


def test_postgres_youtube_store_fails_closed_when_dsn_is_missing(monkeypatch) -> None:
    settings = Settings(
        youtube_store_backend="postgres",
        postgres_dsn_env="TEST_YOUTUBE_POSTGRES_DSN",
    )
    monkeypatch.delenv("TEST_YOUTUBE_POSTGRES_DSN", raising=False)

    with pytest.raises(PostgresConfigurationError):
        get_youtube_memory_store(settings)

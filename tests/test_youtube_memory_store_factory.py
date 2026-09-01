from __future__ import annotations

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError
from app.db.youtube_memory_store import YouTubeMemoryStore
from app.db.youtube_memory_store_factory import get_youtube_memory_store


def test_youtube_store_defaults_to_sqlite(tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "memory.db"))

    store = get_youtube_memory_store(settings)

    assert isinstance(store, YouTubeMemoryStore)


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
        "app.db.youtube_memory_store_factory.PostgresYouTubeMemoryStore",
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

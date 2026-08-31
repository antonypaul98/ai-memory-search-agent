from __future__ import annotations

import pytest

from app.config import Settings
from app.db.memory_store import MemoryStore
from app.db import memory_store_factory
from app.db.memory_store_factory import get_memory_store, reset_memory_store_factory_cache
from app.db.postgres_runtime import PostgresConfigurationError


@pytest.fixture(autouse=True)
def _reset_factory_cache():
    reset_memory_store_factory_cache()
    yield
    reset_memory_store_factory_cache()


def test_canonical_memory_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "memory.db"))

    store = get_memory_store(settings)

    assert isinstance(store, MemoryStore)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_memory_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_TEST_DATABASE_URL"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        get_memory_store(settings)


def test_postgres_selection_initializes_schema_and_reuses_store(monkeypatch):
    calls: list[object] = []
    connection_factory = object()

    class FakePostgresMemoryStore:
        def __init__(self, settings, resolved_factory):
            calls.append(("store", settings.memory_store_backend, resolved_factory))

    monkeypatch.setattr(
        memory_store_factory,
        "get_postgres_connection_factory",
        lambda settings: connection_factory,
    )
    monkeypatch.setattr(
        memory_store_factory,
        "ensure_postgres_memory_schema",
        lambda resolved_factory: calls.append(("schema", resolved_factory)),
    )
    monkeypatch.setattr(memory_store_factory, "PostgresMemoryStore", FakePostgresMemoryStore)
    settings = Settings(memory_store_backend="postgres")

    first = get_memory_store(settings)
    second = get_memory_store(settings)

    assert first is second
    assert calls == [
        ("schema", connection_factory),
        ("store", "postgres", connection_factory),
    ]


def test_factory_cache_key_never_contains_dsn_secret(monkeypatch):
    monkeypatch.setenv("P03_SECRET_DSN", "postgresql://user:super-secret@example/db")
    monkeypatch.setattr(
        memory_store_factory,
        "get_postgres_connection_factory",
        lambda settings: object(),
    )
    monkeypatch.setattr(memory_store_factory, "ensure_postgres_memory_schema", lambda factory: None)
    monkeypatch.setattr(memory_store_factory, "PostgresMemoryStore", lambda settings, factory: object())

    get_memory_store(Settings(memory_store_backend="postgres", postgres_dsn_env="P03_SECRET_DSN"))

    keys = " ".join(memory_store_factory._MEMORY_STORES)
    assert "super-secret" not in keys
    assert "postgresql://" not in keys

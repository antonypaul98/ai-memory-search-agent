"""Configured canonical-memory persistence selection for P-03."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore
from app.db.postgres_memory_store import PostgresMemoryStore, ensure_postgres_memory_schema
from app.db.postgres_runtime import get_postgres_connection_factory


_MEMORY_STORES: dict[str, MemoryStore | PostgresMemoryStore] = {}


def get_memory_store(settings: Settings | None = None) -> MemoryStore | PostgresMemoryStore:
    """Return the explicitly configured canonical memory store.

    SQLite remains the safe local/default profile. Selecting Postgres is
    fail-closed: the shared runtime must resolve a valid environment-owned DSN,
    otherwise construction raises rather than silently persisting locally.
    """
    settings = settings or get_settings()
    if settings.memory_store_backend == "sqlite":
        key = f"sqlite:{settings.sqlite_path}"
        if key not in _MEMORY_STORES:
            _MEMORY_STORES[key] = MemoryStore(settings)
        return _MEMORY_STORES[key]

    key = f"postgres:{settings.postgres_dsn_env}:{settings.postgres_connect_timeout_sec}"
    if key not in _MEMORY_STORES:
        connection_factory = get_postgres_connection_factory(settings)
        ensure_postgres_memory_schema(connection_factory)
        _MEMORY_STORES[key] = PostgresMemoryStore(settings, connection_factory)
    return _MEMORY_STORES[key]


def reset_memory_store_factory_cache() -> None:
    _MEMORY_STORES.clear()

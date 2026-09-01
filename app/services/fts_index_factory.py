"""Configured lexical-index selection for the P-03 FTS cutover."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.db.postgres_fts_index import PostgresFTSIndex
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.fts_index import FTSIndex


_FTS_INDEXES: dict[str, FTSIndex | PostgresFTSIndex] = {}


def get_fts_index(settings: Settings | None = None) -> FTSIndex | PostgresFTSIndex:
    """Return the explicitly configured lexical index.

    SQLite remains available for the local single-user profile. It is not safe
    for authenticated use because the legacy FTS5 table has no tenant column,
    so authenticated SQLite selection fails closed instead of risking cross-user
    lexical reads or mutations. Postgres requires the environment-owned DSN and
    preserves explicit tenant identity on every operation.
    """
    settings = settings or get_settings()
    if settings.fts_store_backend == "sqlite":
        if settings.auth_enabled:
            raise RuntimeError(
                "Authenticated lexical search requires FTS_STORE_BACKEND=postgres; "
                "the legacy SQLite FTS index is not tenant-scoped"
            )
        key = f"sqlite:{settings.sqlite_path}"
        if key not in _FTS_INDEXES:
            _FTS_INDEXES[key] = FTSIndex(settings)
        return _FTS_INDEXES[key]

    key = f"postgres:{settings.postgres_dsn_env}:{settings.postgres_connect_timeout_sec}"
    if key not in _FTS_INDEXES:
        _FTS_INDEXES[key] = PostgresFTSIndex(get_postgres_connection_factory(settings))
    return _FTS_INDEXES[key]


def reset_fts_index_factory_cache() -> None:
    _FTS_INDEXES.clear()

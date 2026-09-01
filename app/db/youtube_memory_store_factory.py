"""Backend selection for the complete YouTube persistence boundary.

The selected store owns YouTube memories together with pipeline history,
retry/dead-letter state, and connector metrics. Keeping selection in one place
prevents production from silently splitting that operational state across
SQLite and Postgres.
"""

from __future__ import annotations

from app.config import Settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_youtube_memory_store import PostgresYouTubeMemoryStore
from app.db.sqlite_youtube_memory_store import SQLiteYouTubeMemoryStore


def get_youtube_memory_store(settings: Settings):
    """Return the explicitly selected YouTube store, failing closed on Postgres config."""
    if settings.youtube_store_backend == "sqlite":
        return SQLiteYouTubeMemoryStore(settings)
    if settings.youtube_store_backend == "postgres":
        return PostgresYouTubeMemoryStore(get_postgres_connection_factory(settings))
    raise ValueError(f"Unsupported YouTube store backend: {settings.youtube_store_backend}")

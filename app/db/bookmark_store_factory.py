"""Backend selection for browser-bookmark persistence."""

from __future__ import annotations

from app.config import Settings
from app.db.bookmark_store import BookmarkStore
from app.db.postgres_bookmark_store import PostgresBookmarkStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_bookmark_store(settings: Settings):
    if settings.bookmark_store_backend == "sqlite":
        return BookmarkStore(settings)
    if settings.bookmark_store_backend == "postgres":
        return PostgresBookmarkStore(get_postgres_connection_factory(settings))
    raise ValueError(f"Unsupported bookmark store backend: {settings.bookmark_store_backend}")

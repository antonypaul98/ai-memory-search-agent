"""Backend selection for cross-connector URL/content deduplication."""

from __future__ import annotations

from app.config import Settings
from app.db.content_url_index_store import ContentUrlIndexStore
from app.db.postgres_content_url_index_store import PostgresContentUrlIndexStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_content_url_index_store(settings: Settings):
    """Keep cross-source dedup state aligned with canonical memory persistence."""
    if settings.memory_store_backend == "sqlite":
        return ContentUrlIndexStore(settings)
    if settings.memory_store_backend == "postgres":
        return PostgresContentUrlIndexStore(get_postgres_connection_factory(settings))
    raise ValueError(f"Unsupported memory store backend: {settings.memory_store_backend}")

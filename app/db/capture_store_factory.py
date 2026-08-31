"""Backend selection for capture-state persistence."""

from __future__ import annotations

from app.config import Settings
from app.db.capture_store import CaptureStore
from app.db.postgres_capture_store import PostgresCaptureStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_capture_store(settings: Settings):
    if settings.capture_store_backend == "sqlite":
        return CaptureStore(settings)
    if settings.capture_store_backend == "postgres":
        return PostgresCaptureStore(get_postgres_connection_factory(settings))
    raise ValueError(f"Unsupported capture store backend: {settings.capture_store_backend}")

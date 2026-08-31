"""Backend selection for import-run execution/history persistence."""

from __future__ import annotations

from app.config import Settings
from app.db.import_run_store import ImportRunStore
from app.db.postgres_import_run_store import PostgresImportRunStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_import_run_store(settings: Settings):
    if settings.import_run_store_backend == "sqlite":
        return ImportRunStore(settings)
    if settings.import_run_store_backend == "postgres":
        return PostgresImportRunStore(get_postgres_connection_factory(settings))
    raise ValueError(f"Unsupported import run store backend: {settings.import_run_store_backend}")

"""Backend selection for import-run execution/history persistence.

Import runs intentionally follow the bookmark persistence backend during this
P-03 slice so the bookmark/import production profile cannot silently split
writes between Postgres and SQLite.
"""

from __future__ import annotations

from app.config import Settings
from app.db.import_run_store import ImportRunStore
from app.db.postgres_import_run_store import PostgresImportRunStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_import_run_store(settings: Settings):
    if settings.bookmark_store_backend == "sqlite":
        return ImportRunStore(settings)
    if settings.bookmark_store_backend == "postgres":
        return PostgresImportRunStore(get_postgres_connection_factory(settings))
    raise ValueError(f"Unsupported bookmark/import store backend: {settings.bookmark_store_backend}")

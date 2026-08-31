"""Configured authentication persistence selection for GAP-02."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.db.auth_store import AuthStore
from app.db.postgres_auth_store import PostgresAuthStore, ensure_postgres_auth_schema
from app.db.postgres_runtime import get_postgres_connection_factory


def get_auth_store(settings: Settings | None = None) -> AuthStore | PostgresAuthStore:
    """Return the explicitly configured auth/session store.

    SQLite remains the safe historical default. Selecting Postgres is fail-closed:
    a missing/invalid environment-owned DSN raises instead of silently using the
    local SQLite database.
    """
    settings = settings or get_settings()
    if settings.auth_store_backend == "sqlite":
        return AuthStore(settings)

    connection_factory = get_postgres_connection_factory(settings)
    ensure_postgres_auth_schema(connection_factory)
    return PostgresAuthStore(settings, connection_factory)

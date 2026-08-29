"""Postgres connection and base job-schema wiring for GAP-02.

Credentials remain environment-owned.  This module resolves only the configured
environment-variable name at runtime, never logs or persists the DSN, and keeps
schema setup separate from backend selection so split-worker safety stays closed
until the full application cutover is validated.
"""

from __future__ import annotations

import os
from typing import Any

from app.config import Settings
from app.db.postgres_job_claims import PostgresJobClaimStore
from app.db.postgres_job_repository import ConnectionFactory


class PostgresConfigurationError(RuntimeError):
    """Raised when the selected Postgres runtime is missing safe configuration."""


def get_postgres_connection_factory(settings: Settings) -> ConnectionFactory:
    """Build a lazy psycopg connection factory without exposing the configured DSN."""
    env_name = settings.postgres_dsn_env.strip()
    if not env_name:
        raise PostgresConfigurationError("POSTGRES_DSN_ENV must name a DSN environment variable")
    dsn = os.getenv(env_name, "").strip()
    if not dsn:
        raise PostgresConfigurationError(
            f"Postgres job storage requires the {env_name} environment variable"
        )
    if settings.postgres_connect_timeout_sec <= 0:
        raise PostgresConfigurationError("POSTGRES_CONNECT_TIMEOUT_SEC must be positive")

    # Import lazily so the historical SQLite-only path remains import-safe.
    import psycopg
    from psycopg.rows import dict_row

    def connect() -> Any:
        return psycopg.connect(
            dsn,
            connect_timeout=settings.postgres_connect_timeout_sec,
            row_factory=dict_row,
        )

    return connect


def ensure_postgres_job_schema(connection_factory: ConnectionFactory, *, lease_seconds: int = 120) -> None:
    """Create the Postgres job persistence surface idempotently.

    Only background-job tables live here; Memory Search canonical records and
    provenance stores are intentionally untouched.  Lease objects are delegated
    to the concurrency primitive that owns their semantics.
    """
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS background_jobs (
                job_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                job_type TEXT NOT NULL,
                playlist_id TEXT,
                playlist_title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                total_videos INTEGER NOT NULL DEFAULT 0,
                queued INTEGER NOT NULL DEFAULT 0,
                processing INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                lease_owner TEXT,
                lease_until TIMESTAMPTZ,
                paused BOOLEAN NOT NULL DEFAULT FALSE,
                force_refresh BOOLEAN NOT NULL DEFAULT FALSE,
                reflection_json TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_items (
                id BIGSERIAL PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES background_jobs(job_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                error TEXT,
                updated_at TIMESTAMPTZ NOT NULL,
                UNIQUE(job_id, item_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_events (
                id BIGSERIAL PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES background_jobs(job_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_background_jobs_runnable
            ON background_jobs(status, paused, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_job_items_claim
            ON job_items(status, updated_at, id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_job_items_tenant
            ON job_items(user_id, job_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_job_events_job
            ON job_events(job_id, id)
            """
        )

    PostgresJobClaimStore(connection_factory, lease_seconds=lease_seconds).ensure_schema()

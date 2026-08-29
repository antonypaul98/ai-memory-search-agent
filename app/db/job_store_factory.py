"""Configured durable job-store selection for GAP-02.

SQLite remains the default. Postgres is selected only when explicitly configured,
uses an environment-indirected DSN, and initializes only the background-job schema.
No credential values are logged or persisted here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings
from app.db.job_store import JobStore
from app.db.postgres_job_store import PostgresJobStore
from app.db.postgres_runtime import (
    ensure_postgres_job_schema,
    get_postgres_connection_factory,
)
from app.db.schema import get_connection, migrate
from app.models.reflection import ReflectionInput


@dataclass(frozen=True)
class JobExecutionContext:
    user_id: str
    reflection: ReflectionInput | None
    force_refresh: bool


def get_job_store(settings: Settings | None = None) -> JobStore | PostgresJobStore:
    """Return the configured authoritative durable job store.

    Selecting Postgres fails closed when its environment-owned DSN is missing or
    invalid. SQLite remains the historical single-node default.
    """
    settings = settings or get_settings()
    if settings.job_store_backend == "sqlite":
        return JobStore(settings)

    connection_factory = get_postgres_connection_factory(settings)
    ensure_postgres_job_schema(
        connection_factory,
        lease_seconds=settings.job_lease_seconds,
    )
    return PostgresJobStore(
        connection_factory,
        lease_seconds=settings.job_lease_seconds,
    )


def get_job_execution_context(
    settings: Settings,
    job_id: str,
) -> JobExecutionContext:
    """Read worker-only execution metadata from the selected durable backend.

    The worker needs tenant ownership plus the original optional reflection and
    refresh flag. Keep this read backend-aware so Postgres workers never fall
    back to the local SQLite file after the durable store is switched.
    """
    if settings.job_store_backend == "sqlite":
        migrate(settings)
        with get_connection(settings) as conn:
            row = conn.execute(
                """
                SELECT user_id, reflection_json, force_refresh
                FROM background_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
    else:
        connection_factory = get_postgres_connection_factory(settings)
        with connection_factory() as conn:
            row = conn.execute(
                """
                SELECT user_id, reflection_json, force_refresh
                FROM background_jobs
                WHERE job_id = %s
                """,
                (job_id,),
            ).fetchone()

    if not row:
        raise KeyError(f"Job not found: {job_id}")

    reflection = _parse_reflection(_value(row, "reflection_json"))
    return JobExecutionContext(
        user_id=str(_value(row, "user_id")),
        reflection=reflection,
        force_refresh=bool(_value(row, "force_refresh")),
    )


def _parse_reflection(raw: Any) -> ReflectionInput | None:
    if not raw:
        return None
    try:
        return ReflectionInput.model_validate(json.loads(str(raw)))
    except Exception:
        # Historical behavior treated malformed optional reflection metadata as
        # absent rather than blocking ingestion. Preserve that fail-soft contract.
        return None


def _value(row: Any, key: str) -> Any:
    """Support sqlite Row, psycopg dict_row, and tuple-like test doubles safely."""
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        index = {"user_id": 0, "reflection_json": 1, "force_refresh": 2}[key]
        return row[index]

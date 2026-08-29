"""Postgres retry/delete primitives for the distributed job-store migration.

SQLite remains the active application JobStore until the remaining CRUD/read
surface and backend wiring are complete and validated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Protocol


class CursorLike(Protocol):
    rowcount: int

    def fetchone(self) -> Any: ...


class ConnectionLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> CursorLike: ...


ConnectionFactory = Callable[[], Any]


class PostgresJobMutationStore:
    """Tenant-safe retry/delete operations for Postgres-backed jobs."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def retry_failed(
        self,
        *,
        job_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> bool:
        """Requeue failed items for a tenant-owned non-cancelled job atomically."""
        _validate_identity(job_id=job_id, user_id=user_id)
        now_dt = _aware_now(now)

        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT status
                FROM background_jobs
                WHERE job_id = %s AND user_id = %s
                FOR UPDATE
                """,
                (job_id, user_id),
            ).fetchone()
            if not row:
                return False
            if _field(row, "status", 0) == "cancelled":
                return False

            conn.execute(
                """
                UPDATE job_items
                SET status = 'queued', error = NULL, updated_at = %s
                WHERE job_id = %s AND user_id = %s AND status = 'failed'
                """,
                (now_dt, job_id, user_id),
            )
            failed_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM job_items
                WHERE job_id = %s AND user_id = %s AND status = 'failed'
                """,
                (job_id, user_id),
            ).fetchone()
            queued_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM job_items
                WHERE job_id = %s AND user_id = %s AND status = 'queued'
                """,
                (job_id, user_id),
            ).fetchone()
            failed = int(_field(failed_row, "count", 0)) if failed_row else 0
            queued = int(_field(queued_row, "count", 0)) if queued_row else 0

            cur = conn.execute(
                """
                UPDATE background_jobs
                SET status = 'queued', failed = %s, queued = %s,
                    finished_at = NULL, paused = FALSE
                WHERE job_id = %s AND user_id = %s
                """,
                (failed, queued, job_id, user_id),
            )
            if not cur.rowcount:
                return False
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, created_at)
                VALUES (%s, 'retried', 'Failed items requeued', %s)
                """,
                (job_id, now_dt),
            )
        return True

    def delete_job(self, *, job_id: str, user_id: str) -> bool:
        """Delete exactly one tenant-owned job and all of its durable queue state."""
        _validate_identity(job_id=job_id, user_id=user_id)

        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT job_id
                FROM background_jobs
                WHERE job_id = %s AND user_id = %s
                FOR UPDATE
                """,
                (job_id, user_id),
            ).fetchone()
            if not row:
                return False

            conn.execute(
                """
                DELETE FROM job_item_leases
                WHERE job_id = %s
                  AND EXISTS (
                    SELECT 1 FROM background_jobs
                    WHERE job_id = %s AND user_id = %s
                  )
                """,
                (job_id, job_id, user_id),
            )
            conn.execute(
                "DELETE FROM job_events WHERE job_id = %s",
                (job_id,),
            )
            conn.execute(
                "DELETE FROM job_items WHERE job_id = %s AND user_id = %s",
                (job_id, user_id),
            )
            cur = conn.execute(
                "DELETE FROM background_jobs WHERE job_id = %s AND user_id = %s",
                (job_id, user_id),
            )
            return bool(cur.rowcount)


def _validate_identity(*, job_id: str, user_id: str) -> None:
    if not job_id.strip():
        raise ValueError("job_id is required")
    if not user_id.strip():
        raise ValueError("user_id is required")


def _aware_now(now: datetime | None) -> datetime:
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now_dt


def _field(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError):
        return row[index]

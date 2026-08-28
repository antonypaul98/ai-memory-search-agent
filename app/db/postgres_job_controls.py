"""Postgres job-control primitives for the distributed queue migration.

This module intentionally covers only the next GAP-02 slice: tenant-scoped
pause/resume and soft-cancel. SQLite remains the application JobStore until the
remaining job CRUD/read surface and backend wiring are migrated and validated.
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


class PostgresJobControlStore:
    """Tenant-safe Postgres controls for user-driven job state changes."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def set_paused(
        self,
        *,
        job_id: str,
        user_id: str,
        paused: bool,
        now: datetime | None = None,
    ) -> bool:
        """Pause or resume a tenant-owned job.

        Resume fails closed for terminal jobs, matching the SQLite JobStore
        contract. The state mutation and durable job event share one transaction.
        """
        _validate_identity(job_id=job_id, user_id=user_id)
        now_dt = _aware_now(now)
        terminal_guard = "" if paused else "AND status NOT IN ('completed', 'cancelled', 'failed')"
        event_type = "paused" if paused else "resumed"

        with self._connection_factory() as conn:
            cur = conn.execute(
                f"""
                UPDATE background_jobs
                SET paused = %s
                WHERE job_id = %s AND user_id = %s
                  {terminal_guard}
                """,
                (paused, job_id, user_id),
            )
            if not cur.rowcount:
                return False
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, created_at)
                VALUES (%s, %s, 'User toggled pause', %s)
                """,
                (job_id, event_type, now_dt),
            )
        return True

    def cancel_job(
        self,
        *,
        job_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> bool:
        """Soft-cancel queued work without disturbing in-flight worker ownership.

        The tenant-owned job row is locked first. Missing, completed, or already
        cancelled jobs produce no writes. Queued items are cancelled, while
        processing items and their leases remain untouched so authoritative
        workers can finish without being impersonated or force-reclaimed.
        """
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
            status = _field(row, "status", 0)
            if status in {"completed", "cancelled"}:
                return False

            conn.execute(
                """
                UPDATE job_items
                SET status = 'cancelled', updated_at = %s
                WHERE job_id = %s AND user_id = %s AND status = 'queued'
                """,
                (now_dt, job_id, user_id),
            )
            queued_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM job_items
                WHERE job_id = %s AND user_id = %s AND status = 'queued'
                """,
                (job_id, user_id),
            ).fetchone()
            queued_left = int(_field(queued_row, "count", 0)) if queued_row else 0
            cur = conn.execute(
                """
                UPDATE background_jobs
                SET status = 'cancelled', paused = TRUE, queued = %s,
                    finished_at = %s
                WHERE job_id = %s AND user_id = %s
                """,
                (queued_left, now_dt, job_id, user_id),
            )
            if not cur.rowcount:
                return False
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, created_at)
                VALUES (%s, 'cancelled', 'Cancelled by user', %s)
                """,
                (job_id, now_dt),
            )
        return True


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

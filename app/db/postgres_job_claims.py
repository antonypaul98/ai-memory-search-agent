"""Postgres-specific atomic worker primitives for distributed job workers.

This module is intentionally narrow: it implements the concurrency-critical
claim/lease/heartbeat/finalization transactions without switching the
application to Postgres yet. The existing SQLite JobStore remains the runtime
source of truth until the remaining persistence methods are migrated and the
backend factory is wired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol


class CursorLike(Protocol):
    rowcount: int

    def fetchone(self) -> Any: ...


class ConnectionLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> CursorLike: ...


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class ClaimedJobItem:
    job_id: str
    item_key: str
    url: str


class PostgresJobClaimStore:
    """Concurrency-safe Postgres claim/lease operations.

    The claim query uses ``FOR UPDATE SKIP LOCKED`` so independent workers can
    claim different rows concurrently without a process-wide mutex. All lease
    and aggregate-counter changes occur in the same transaction as the claim.
    Heartbeat and completion similarly require the current worker lease so a
    stale/reclaimed worker cannot mutate authoritative job state.
    """

    _FINAL_COUNTERS = {
        "completed": "completed",
        "skipped": "skipped",
        "failed": "failed",
    }

    def __init__(self, connection_factory: ConnectionFactory, *, lease_seconds: int = 120) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._connection_factory = connection_factory
        self._lease_seconds = lease_seconds

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_item_leases (
                    job_id TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    lease_until TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (job_id, item_key)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_item_leases_expiry
                ON job_item_leases(lease_until)
                """
            )

    def claim_next_item(
        self,
        *,
        worker_id: str,
        user_id: str | None = None,
        now: datetime | None = None,
    ) -> ClaimedJobItem | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")

        now_dt = _aware_now(now)
        lease_until = now_dt + timedelta(seconds=self._lease_seconds)
        stale_without_lease = now_dt - timedelta(seconds=self._lease_seconds)

        user_predicate = "AND ji.user_id = %s" if user_id else ""
        params: list[Any] = [now_dt, stale_without_lease]
        if user_id:
            params.append(user_id)
        params.append(now_dt)

        claim_sql = f"""
            WITH candidate AS (
                SELECT ji.id, ji.job_id, ji.item_key, ji.url, ji.status AS previous_status
                FROM job_items ji
                JOIN background_jobs bj ON bj.job_id = ji.job_id
                LEFT JOIN job_item_leases jl
                  ON jl.job_id = ji.job_id AND jl.item_key = ji.item_key
                WHERE bj.paused = FALSE
                  AND bj.status IN ('queued', 'running')
                  AND (
                    ji.status = 'queued'
                    OR (
                      ji.status = 'processing'
                      AND (
                        (jl.lease_until IS NOT NULL AND jl.lease_until <= %s)
                        OR (jl.lease_until IS NULL AND ji.updated_at <= %s)
                      )
                    )
                  )
                  {user_predicate}
                ORDER BY CASE WHEN ji.status = 'processing' THEN 0 ELSE 1 END, ji.id
                FOR UPDATE OF ji SKIP LOCKED
                LIMIT 1
            )
            UPDATE job_items ji
            SET status = 'processing', updated_at = %s, error = NULL
            FROM candidate c
            WHERE ji.id = c.id
            RETURNING c.job_id, c.item_key, c.url, c.previous_status
        """

        with self._connection_factory() as conn:
            row = conn.execute(claim_sql, tuple(params)).fetchone()
            if not row:
                return None

            job_id = _field(row, "job_id", 0)
            item_key = _field(row, "item_key", 1)
            url = _field(row, "url", 2)
            previous_status = _field(row, "previous_status", 3)

            conn.execute(
                """
                INSERT INTO job_item_leases (job_id, item_key, worker_id, lease_until, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (job_id, item_key) DO UPDATE SET
                    worker_id = EXCLUDED.worker_id,
                    lease_until = EXCLUDED.lease_until,
                    updated_at = EXCLUDED.updated_at
                """,
                (job_id, item_key, worker_id, lease_until, now_dt),
            )

            if previous_status == "queued":
                conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'running', started_at = COALESCE(started_at, %s),
                        processing = processing + 1,
                        queued = GREATEST(0, queued - 1),
                        lease_owner = %s, lease_until = %s
                    WHERE job_id = %s AND status IN ('queued', 'running')
                    """,
                    (now_dt, worker_id, lease_until, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'running', lease_owner = %s, lease_until = %s
                    WHERE job_id = %s AND status IN ('queued', 'running')
                    """,
                    (worker_id, lease_until, job_id),
                )
                conn.execute(
                    """
                    INSERT INTO job_events (job_id, event_type, message, created_at)
                    VALUES (%s, 'reclaimed', 'Expired item claim recovered', %s)
                    """,
                    (job_id, now_dt),
                )

        return ClaimedJobItem(job_id=job_id, item_key=item_key, url=url)

    def heartbeat_item(
        self,
        *,
        job_id: str,
        item_key: str,
        worker_id: str,
        now: datetime | None = None,
    ) -> bool:
        """Extend a processing lease only while ``worker_id`` still owns it."""
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        now_dt = _aware_now(now)
        lease_until = now_dt + timedelta(seconds=self._lease_seconds)

        with self._connection_factory() as conn:
            cur = conn.execute(
                """
                UPDATE job_item_leases jl
                SET lease_until = %s, updated_at = %s
                WHERE jl.job_id = %s AND jl.item_key = %s AND jl.worker_id = %s
                  AND EXISTS (
                    SELECT 1 FROM job_items ji
                    WHERE ji.job_id = jl.job_id
                      AND ji.item_key = jl.item_key
                      AND ji.status = 'processing'
                  )
                """,
                (lease_until, now_dt, job_id, item_key, worker_id),
            )
            if not cur.rowcount:
                return False
            conn.execute(
                """
                UPDATE job_items
                SET updated_at = %s
                WHERE job_id = %s AND item_key = %s AND status = 'processing'
                """,
                (now_dt, job_id, item_key),
            )
            conn.execute(
                """
                UPDATE background_jobs
                SET lease_owner = %s, lease_until = %s
                WHERE job_id = %s AND status IN ('queued', 'running')
                """,
                (worker_id, lease_until, job_id),
            )
        return True

    def complete_item(
        self,
        *,
        job_id: str,
        item_key: str,
        status: str,
        worker_id: str,
        error: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Finalize a processing item only for the authoritative lease owner.

        The worker ownership check and item mutation happen in one statement,
        preventing a worker whose lease was reclaimed from reporting a late
        success or failure. Aggregate counters and terminal job state are then
        updated in the same transaction.
        """
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        counter = self._FINAL_COUNTERS.get(status)
        if counter is None:
            raise ValueError("status must be completed, skipped, or failed")
        now_dt = _aware_now(now)

        with self._connection_factory() as conn:
            cur = conn.execute(
                """
                UPDATE job_items ji
                SET status = %s, error = %s, updated_at = %s
                WHERE ji.job_id = %s AND ji.item_key = %s AND ji.status = 'processing'
                  AND EXISTS (
                    SELECT 1 FROM job_item_leases jl
                    WHERE jl.job_id = ji.job_id
                      AND jl.item_key = ji.item_key
                      AND jl.worker_id = %s
                  )
                """,
                (status, error, now_dt, job_id, item_key, worker_id),
            )
            if not cur.rowcount:
                return False

            conn.execute(
                """
                DELETE FROM job_item_leases
                WHERE job_id = %s AND item_key = %s AND worker_id = %s
                """,
                (job_id, item_key, worker_id),
            )
            conn.execute(
                f"""
                UPDATE background_jobs
                SET processing = GREATEST(0, processing - 1),
                    {counter} = {counter} + 1
                WHERE job_id = %s
                """,
                (job_id,),
            )
            remaining_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM job_items
                WHERE job_id = %s AND status IN ('queued', 'processing')
                """,
                (job_id,),
            ).fetchone()
            remaining = int(_field(remaining_row, "count", 0)) if remaining_row else 0
            if remaining == 0:
                finished = conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'completed', finished_at = %s,
                        lease_owner = NULL, lease_until = NULL
                    WHERE job_id = %s AND status <> 'cancelled'
                    """,
                    (now_dt, job_id),
                )
                if finished.rowcount:
                    conn.execute(
                        """
                        INSERT INTO job_events (job_id, event_type, message, created_at)
                        VALUES (%s, 'completed', 'Job finished', %s)
                        """,
                        (job_id, now_dt),
                    )
        return True


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

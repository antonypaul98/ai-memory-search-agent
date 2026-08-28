"""Postgres-specific atomic claim primitive for distributed job workers.

This module is intentionally narrow: it implements the concurrency-critical
claim/lease transaction without switching the application to Postgres yet.
The existing SQLite JobStore remains the runtime source of truth until the
remaining persistence methods are migrated and the backend factory is wired.
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
    claim different rows concurrently without a process-wide mutex.  All lease
    and aggregate-counter changes occur in the same transaction as the claim.
    """

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

        now_dt = now or datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            raise ValueError("now must be timezone-aware")
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
                WHERE bj.paused = 0
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


def _field(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError):
        return row[index]

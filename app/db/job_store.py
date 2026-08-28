"""SQLite-backed persistent job queue."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db.schema import get_connection, migrate
from app.models.job import BackgroundJob, JobDetailResponse, JobItemStatus
from app.models.reflection import ReflectionInput
from app.services.playlist_service import PlaylistVideoEntry

logger = logging.getLogger(__name__)


class JobStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)
        self._ensure_item_lease_table()

    def _ensure_item_lease_table(self) -> None:
        """Create the F-35 auxiliary lease table without changing durable job payloads."""
        with get_connection(self._settings) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_item_leases (
                    job_id TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    lease_until TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, item_key)
                );
                CREATE INDEX IF NOT EXISTS idx_job_item_leases_expiry
                    ON job_item_leases(lease_until);
                """
            )

    def create_playlist_job(
        self,
        *,
        user_id: str,
        playlist_id: str,
        playlist_title: str,
        entries: list[PlaylistVideoEntry],
        reflection: ReflectionInput | None,
        force_refresh: bool,
    ) -> BackgroundJob:
        job_id = str(uuid.uuid4())
        now = _utc_now()
        reflection_json = reflection.model_dump_json() if reflection else ""
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO background_jobs (
                    job_id, user_id, job_type, playlist_id, playlist_title, status,
                    total_videos, queued, created_at, force_refresh, reflection_json
                ) VALUES (?, ?, 'playlist_ingest', ?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    user_id,
                    playlist_id,
                    playlist_title,
                    len(entries),
                    len(entries),
                    now,
                    1 if force_refresh else 0,
                    reflection_json,
                ),
            )
            for entry in entries:
                conn.execute(
                    """
                    INSERT INTO job_items (job_id, user_id, item_key, url, title, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'queued', ?)
                    """,
                    (job_id, user_id, entry.video_id, entry.url, entry.title, now),
                )
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, created_at)
                VALUES (?, 'created', ?, ?)
                """,
                (job_id, f"Queued {len(entries)} videos", now),
            )
        logger.info(
            "playlist_job_created job_id=%s user_id=%s videos=%s playlist_id=%s",
            job_id,
            user_id,
            len(entries),
            playlist_id,
        )
        return self.get_job(job_id, user_id=user_id)

    def get_job(self, job_id: str, *, user_id: str) -> BackgroundJob:
        row = self._fetch_job_row(job_id, user_id)
        return _row_to_job(row)

    def get_job_detail(self, job_id: str, *, user_id: str) -> JobDetailResponse:
        job = self.get_job(job_id, user_id=user_id)
        with get_connection(self._settings) as conn:
            items = conn.execute(
                """
                SELECT item_key, url, title, status, error FROM job_items
                WHERE job_id = ? AND user_id = ? ORDER BY id
                """,
                (job_id, user_id),
            ).fetchall()
            events = conn.execute(
                """
                SELECT message FROM job_events WHERE job_id = ? ORDER BY id DESC LIMIT 20
                """,
                (job_id,),
            ).fetchall()
        return JobDetailResponse(
            **job.model_dump(),
            items=[
                JobItemStatus(
                    item_key=r["item_key"],
                    url=r["url"],
                    title=r["title"],
                    status=r["status"],
                    error=r["error"],
                )
                for r in items
            ],
            events=[r["message"] for r in reversed(events)],
        )

    def list_runnable_jobs(self) -> list[str]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT job_id FROM background_jobs
                WHERE status IN ('queued', 'running') AND paused = 0
                ORDER BY created_at
                """,
            ).fetchall()
        return [r["job_id"] for r in rows]

    def claim_next_item(self, *, worker_id: str, user_id: str | None = None) -> tuple[str, str, str] | None:
        """Atomically claim queued work or take over an expired processing claim."""
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=self._settings.job_lease_seconds)).isoformat()
        stale_without_lease = (now_dt - timedelta(seconds=self._settings.job_lease_seconds)).isoformat()

        with get_connection(self._settings) as conn:
            # BEGIN IMMEDIATE serializes claim decisions for this SQLite claim store.
            # F-35's later Postgres cutover will replace this local writer boundary.
            conn.execute("BEGIN IMMEDIATE")
            user_clause = " AND ji.user_id = ?" if user_id else ""
            params: list[str] = [now, stale_without_lease]
            if user_id:
                params.append(user_id)
            row = conn.execute(
                f"""
                SELECT ji.id, ji.job_id, ji.item_key, ji.url, ji.status
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
                        (jl.lease_until IS NOT NULL AND jl.lease_until <= ?)
                        OR (jl.lease_until IS NULL AND ji.updated_at <= ?)
                      )
                    )
                  )
                  {user_clause}
                ORDER BY CASE WHEN ji.status = 'processing' THEN 0 ELSE 1 END, ji.id
                LIMIT 1
                """,
                params,
            ).fetchone()
            if not row:
                return None

            previous_status = row["status"]
            conn.execute(
                """
                UPDATE job_items
                SET status = 'processing', updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (now, row["id"]),
            )
            conn.execute(
                """
                INSERT INTO job_item_leases (job_id, item_key, worker_id, lease_until, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id, item_key) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    lease_until = excluded.lease_until,
                    updated_at = excluded.updated_at
                """,
                (row["job_id"], row["item_key"], worker_id, lease_until, now),
            )
            if previous_status == "queued":
                conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'running', started_at = COALESCE(started_at, ?),
                        processing = processing + 1, queued = MAX(0, queued - 1),
                        lease_owner = ?, lease_until = ?
                    WHERE job_id = ? AND status IN ('queued', 'running')
                    """,
                    (now, worker_id, lease_until, row["job_id"]),
                )
            else:
                # Taking over expired processing work keeps aggregate counters unchanged.
                conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'running', lease_owner = ?, lease_until = ?
                    WHERE job_id = ? AND status IN ('queued', 'running')
                    """,
                    (worker_id, lease_until, row["job_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO job_events (job_id, event_type, message, created_at)
                    VALUES (?, 'reclaimed', 'Expired item claim recovered', ?)
                    """,
                    (row["job_id"], now),
                )
        return row["job_id"], row["item_key"], row["url"]

    def heartbeat_item(self, *, job_id: str, item_key: str, worker_id: str) -> bool:
        """Extend an active claim only when it is still owned by ``worker_id``."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=self._settings.job_lease_seconds)).isoformat()
        with get_connection(self._settings) as conn:
            cur = conn.execute(
                """
                UPDATE job_item_leases
                SET lease_until = ?, updated_at = ?
                WHERE job_id = ? AND item_key = ? AND worker_id = ?
                  AND EXISTS (
                    SELECT 1 FROM job_items ji
                    WHERE ji.job_id = job_item_leases.job_id
                      AND ji.item_key = job_item_leases.item_key
                      AND ji.status = 'processing'
                  )
                """,
                (lease_until, now, job_id, item_key, worker_id),
            )
            if not cur.rowcount:
                return False
            conn.execute(
                """
                UPDATE job_items SET updated_at = ?
                WHERE job_id = ? AND item_key = ? AND status = 'processing'
                """,
                (now, job_id, item_key),
            )
        return True

    def complete_item(
        self,
        *,
        job_id: str,
        item_key: str,
        status: str,
        error: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        """Finalize an item; worker-owned completions fail closed after lease takeover."""
        now = _utc_now()
        with get_connection(self._settings) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if worker_id is not None:
                owner = conn.execute(
                    """
                    SELECT worker_id FROM job_item_leases
                    WHERE job_id = ? AND item_key = ?
                    """,
                    (job_id, item_key),
                ).fetchone()
                if not owner or owner["worker_id"] != worker_id:
                    return False
                cur = conn.execute(
                    """
                    UPDATE job_items SET status = ?, error = ?, updated_at = ?
                    WHERE job_id = ? AND item_key = ? AND status = 'processing'
                    """,
                    (status, error, now, job_id, item_key),
                )
                if not cur.rowcount:
                    return False
            else:
                cur = conn.execute(
                    """
                    UPDATE job_items SET status = ?, error = ?, updated_at = ?
                    WHERE job_id = ? AND item_key = ? AND status = 'processing'
                    """,
                    (status, error, now, job_id, item_key),
                )
                if not cur.rowcount:
                    return False

            conn.execute(
                "DELETE FROM job_item_leases WHERE job_id = ? AND item_key = ?",
                (job_id, item_key),
            )
            field_map = {
                "completed": "completed",
                "skipped": "skipped",
                "failed": "failed",
            }
            column = field_map.get(status, "completed")
            conn.execute(
                f"""
                UPDATE background_jobs
                SET processing = MAX(0, processing - 1),
                    {column} = {column} + 1
                WHERE job_id = ?
                """,
                (job_id,),
            )
            remaining = conn.execute(
                "SELECT COUNT(*) AS c FROM job_items WHERE job_id = ? AND status IN ('queued', 'processing')",
                (job_id,),
            ).fetchone()["c"]
            if remaining == 0:
                # Do not resurrect a cancelled job when in-flight items finish.
                cur = conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'completed', finished_at = ?
                    WHERE job_id = ? AND status NOT IN ('cancelled')
                    """,
                    (now, job_id),
                )
                if cur.rowcount:
                    conn.execute(
                        "INSERT INTO job_events (job_id, event_type, message, created_at) VALUES (?, 'completed', 'Job finished', ?)",
                        (job_id, now),
                    )
        return True

    def set_paused(self, job_id: str, *, user_id: str, paused: bool) -> BackgroundJob:
        row = self._fetch_job_row(job_id, user_id)
        if row["status"] in {"completed", "cancelled", "failed"} and not paused:
            raise AppError(f"Cannot resume a {row['status']} job.")
        with get_connection(self._settings) as conn:
            conn.execute(
                "UPDATE background_jobs SET paused = ? WHERE job_id = ? AND user_id = ?",
                (1 if paused else 0, job_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, "paused" if paused else "resumed", "User toggled pause", _utc_now()),
            )
        return self.get_job(job_id, user_id=user_id)

    def cancel_job(self, job_id: str, *, user_id: str) -> BackgroundJob:
        """Soft-cancel: stop claiming new items; keep history for the progress UI."""
        row = self._fetch_job_row(job_id, user_id)
        if row["status"] in {"completed", "cancelled"}:
            return self.get_job(job_id, user_id=user_id)
        now = _utc_now()
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                UPDATE job_items SET status = 'cancelled', updated_at = ?
                WHERE job_id = ? AND user_id = ? AND status = 'queued'
                """,
                (now, job_id, user_id),
            )
            queued_left = conn.execute(
                "SELECT COUNT(*) AS c FROM job_items WHERE job_id = ? AND status = 'queued'",
                (job_id,),
            ).fetchone()["c"]
            conn.execute(
                """
                UPDATE background_jobs
                SET status = 'cancelled', paused = 1, queued = ?, finished_at = ?
                WHERE job_id = ? AND user_id = ?
                """,
                (queued_left, now, job_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, created_at)
                VALUES (?, 'cancelled', 'Cancelled by user', ?)
                """,
                (job_id, now),
            )
        logger.info("playlist_job_cancelled job_id=%s user_id=%s", job_id, user_id)
        return self.get_job(job_id, user_id=user_id)

    def retry_failed(self, job_id: str, *, user_id: str) -> BackgroundJob:
        row = self._fetch_job_row(job_id, user_id)
        if row["status"] == "cancelled":
            raise AppError("Cannot retry a cancelled job. Start a new playlist import.")
        now = _utc_now()
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                UPDATE job_items SET status = 'queued', error = NULL, updated_at = ?
                WHERE job_id = ? AND user_id = ? AND status = 'failed'
                """,
                (now, job_id, user_id),
            )
            failed = conn.execute(
                "SELECT COUNT(*) AS c FROM job_items WHERE job_id = ? AND status = 'failed'",
                (job_id,),
            ).fetchone()["c"]
            queued = conn.execute(
                "SELECT COUNT(*) AS c FROM job_items WHERE job_id = ? AND status = 'queued'",
                (job_id,),
            ).fetchone()["c"]
            conn.execute(
                """
                UPDATE background_jobs
                SET status = 'queued', failed = ?, queued = ?, finished_at = NULL, paused = 0
                WHERE job_id = ? AND user_id = ?
                """,
                (failed, queued, job_id, user_id),
            )
        return self.get_job(job_id, user_id=user_id)

    def delete_job(self, job_id: str, *, user_id: str) -> None:
        self._fetch_job_row(job_id, user_id)
        with get_connection(self._settings) as conn:
            conn.execute("DELETE FROM job_events WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM job_item_leases WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM job_items WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM background_jobs WHERE job_id = ? AND user_id = ?", (job_id, user_id))

    def _fetch_job_row(self, job_id: str, user_id: str):
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM background_jobs WHERE job_id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
        if not row:
            raise KeyError(f"Job not found: {job_id}")
        return row


def _row_to_job(row) -> BackgroundJob:
    est = None
    completed = int(row["completed"]) + int(row["skipped"]) + int(row["failed"])
    total = int(row["total_videos"])
    if completed > 0 and row["started_at"] and total > completed:
        # rough estimate only
        est = float(max(1, total - completed) * 8)
    return BackgroundJob(
        job_id=row["job_id"],
        user_id=row["user_id"],
        job_type=row["job_type"],
        playlist_id=row["playlist_id"],
        playlist_title=row["playlist_title"] or "",
        total_videos=int(row["total_videos"]),
        queued=int(row["queued"]),
        processing=int(row["processing"]),
        completed=int(row["completed"]),
        skipped=int(row["skipped"]),
        failed=int(row["failed"]),
        status=row["status"],
        error_summary=row["error_summary"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        paused=bool(row["paused"]),
        estimated_remaining_sec=est,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

"""Tenant-safe Postgres persistence for background job creation and reads.

This repository covers the non-worker CRUD/read surface needed before the
application can safely switch the job backend away from SQLite. Concurrency-
critical claim/lease and control mutations remain in the dedicated Postgres
stores until the backend facade is wired.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from app.models.job import BackgroundJob, JobDetailResponse, JobItemStatus
from app.models.reflection import ReflectionInput
from app.services.playlist_service import PlaylistVideoEntry


class CursorLike(Protocol):
    def fetchone(self) -> Any: ...
    def fetchall(self) -> list[Any]: ...


class ConnectionLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> CursorLike: ...


ConnectionFactory = Callable[[], Any]


class PostgresJobRepository:
    """Postgres create/read/detail/list operations with strict tenant scoping."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def create_playlist_job(
        self,
        *,
        user_id: str,
        playlist_id: str,
        playlist_title: str,
        entries: list[PlaylistVideoEntry],
        reflection: ReflectionInput | None,
        force_refresh: bool,
        job_id: str | None = None,
        now: datetime | None = None,
    ) -> BackgroundJob:
        _require("user_id", user_id)
        _require("playlist_id", playlist_id)
        job_id = job_id or str(uuid.uuid4())
        _require("job_id", job_id)
        now_dt = _aware_now(now)
        reflection_json = reflection.model_dump_json() if reflection else ""

        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO background_jobs (
                    job_id, user_id, job_type, playlist_id, playlist_title, status,
                    total_videos, queued, created_at, force_refresh, reflection_json
                ) VALUES (%s, %s, 'playlist_ingest', %s, %s, 'queued', %s, %s, %s, %s, %s)
                """,
                (
                    job_id,
                    user_id,
                    playlist_id,
                    playlist_title,
                    len(entries),
                    len(entries),
                    now_dt,
                    bool(force_refresh),
                    reflection_json,
                ),
            )
            for entry in entries:
                conn.execute(
                    """
                    INSERT INTO job_items (job_id, user_id, item_key, url, title, status, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'queued', %s)
                    """,
                    (job_id, user_id, entry.video_id, entry.url, entry.title, now_dt),
                )
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, created_at)
                VALUES (%s, 'created', %s, %s)
                """,
                (job_id, f"Queued {len(entries)} videos", now_dt),
            )
        return self.get_job(job_id, user_id=user_id)

    def get_job(self, job_id: str, *, user_id: str) -> BackgroundJob:
        _require("job_id", job_id)
        _require("user_id", user_id)
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM background_jobs WHERE job_id = %s AND user_id = %s",
                (job_id, user_id),
            ).fetchone()
        if not row:
            raise KeyError(f"Job not found: {job_id}")
        return _row_to_job(row)

    def get_job_detail(self, job_id: str, *, user_id: str) -> JobDetailResponse:
        job = self.get_job(job_id, user_id=user_id)
        with self._connection_factory() as conn:
            items = conn.execute(
                """
                SELECT item_key, url, title, status, error
                FROM job_items
                WHERE job_id = %s AND user_id = %s
                ORDER BY id
                """,
                (job_id, user_id),
            ).fetchall()
            events = conn.execute(
                """
                SELECT je.message
                FROM job_events je
                WHERE je.job_id = %s
                  AND EXISTS (
                    SELECT 1 FROM background_jobs bj
                    WHERE bj.job_id = je.job_id AND bj.user_id = %s
                  )
                ORDER BY je.id DESC
                LIMIT 20
                """,
                (job_id, user_id),
            ).fetchall()
        return JobDetailResponse(
            **job.model_dump(),
            items=[
                JobItemStatus(
                    item_key=_field(row, "item_key", 0),
                    url=_field(row, "url", 1),
                    title=_field(row, "title", 2) or "",
                    status=_field(row, "status", 3),
                    error=_field(row, "error", 4),
                )
                for row in items
            ],
            events=[_field(row, "message", 0) for row in reversed(events)],
        )

    def list_runnable_jobs(self, *, user_id: str | None = None) -> list[str]:
        params: tuple[Any, ...] = ()
        tenant_sql = ""
        if user_id is not None:
            _require("user_id", user_id)
            tenant_sql = "AND user_id = %s"
            params = (user_id,)
        with self._connection_factory() as conn:
            rows = conn.execute(
                f"""
                SELECT job_id FROM background_jobs
                WHERE status IN ('queued', 'running') AND paused = FALSE
                {tenant_sql}
                ORDER BY created_at
                """,
                params,
            ).fetchall()
        return [_field(row, "job_id", 0) for row in rows]


def _row_to_job(row: Any) -> BackgroundJob:
    completed = int(_field(row, "completed", 7)) + int(_field(row, "skipped", 8)) + int(_field(row, "failed", 9))
    total = int(_field(row, "total_videos", 4))
    started_at = _field(row, "started_at", 13)
    estimated = None
    if completed > 0 and started_at and total > completed:
        estimated = float(max(1, total - completed) * 8)
    return BackgroundJob(
        job_id=_field(row, "job_id", 0),
        user_id=_field(row, "user_id", 1),
        job_type=_field(row, "job_type", 2),
        playlist_id=_field(row, "playlist_id", 3),
        playlist_title=_field(row, "playlist_title", 5) or "",
        total_videos=total,
        queued=int(_field(row, "queued", 6)),
        processing=int(_field(row, "processing", 10)),
        completed=int(_field(row, "completed", 7)),
        skipped=int(_field(row, "skipped", 8)),
        failed=int(_field(row, "failed", 9)),
        status=_field(row, "status", 11),
        error_summary=_field(row, "error_summary", 12),
        created_at=_iso(_field(row, "created_at", 14)),
        started_at=_iso(started_at),
        finished_at=_iso(_field(row, "finished_at", 15)),
        paused=bool(_field(row, "paused", 16)),
        estimated_remaining_sec=estimated,
    )


def _field(row: Any, name: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[name]
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Postgres job timestamps must be timezone-aware")
        return value.isoformat()
    return str(value)


def _aware_now(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return result


def _require(name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} is required")

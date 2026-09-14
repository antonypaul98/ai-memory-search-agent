"""Safe, idempotent SQLite -> Postgres migration for review schedules.

The SQLite source is opened read-only. Existing Postgres schedule rows are never
overwritten, so target-side review progress remains authoritative on retries.
Reports expose counts only; schedule timestamps/results, DSNs and credentials are
never returned.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_review_schedule_store import PostgresReviewScheduleStore
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class ReviewScheduleMigrationPreview:
    schedules: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewScheduleMigrationReport:
    schedules_seen: int
    schedules_inserted: int
    schedules_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_review_schedule_migration(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
) -> ReviewScheduleMigrationPreview:
    """Return count-only source information without contacting Postgres."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    with _open_source_read_only(settings) as conn:
        where, params = _tenant_filter(user_id)
        schedules = int(
            conn.execute(
                f"SELECT COUNT(*) FROM memory_review_schedule{where}", params
            ).fetchone()[0]
        )
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM memory_review_schedule{where}",
                params,
            ).fetchone()[0]
        )
    return ReviewScheduleMigrationPreview(schedules=schedules, tenants=tenants)


def migrate_review_schedules_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> ReviewScheduleMigrationReport:
    """Insert missing SQLite review schedules without overwriting target state."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresReviewScheduleStore(factory)

    with _open_source_read_only(settings) as source:
        where, params = _tenant_filter(user_id)
        rows = source.execute(
            "SELECT user_id, video_id, last_reviewed_at, next_review_at, "
            "review_count, last_result, updated_at "
            f"FROM memory_review_schedule{where} ORDER BY user_id, video_id",
            params,
        ).fetchall()

    inserted = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """
                INSERT INTO memory_review_schedule (
                    user_id, video_id, last_reviewed_at, next_review_at,
                    review_count, last_result, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, video_id) DO NOTHING
                """,
                tuple(row),
            )
            inserted += max(int(cur.rowcount or 0), 0)

    return ReviewScheduleMigrationReport(
        schedules_seen=len(rows),
        schedules_inserted=inserted,
        schedules_skipped_existing=len(rows) - inserted,
    )


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _normalize_user_id(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    value = user_id.strip()
    if not value:
        raise ValueError("user_id must not be blank")
    return value


def _tenant_filter(user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    if user_id is None:
        return "", ()
    return " WHERE user_id = ?", (user_id,)

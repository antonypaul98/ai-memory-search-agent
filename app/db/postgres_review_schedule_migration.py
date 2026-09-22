"""Preview-first transfer of explicitly owned review schedules to Postgres."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.db.account_erasure_fence import require_active_tenant
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


_COLUMNS = (
    "user_id", "video_id", "last_reviewed_at", "next_review_at",
    "review_count", "last_result", "updated_at",
)


def _source_rows(settings: Settings, user_id: str | None) -> list[tuple]:
    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip() or user_id != user_id.strip()):
        raise ValueError("user_id must not be blank or padded")
    source = Path(settings.sqlite_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError("SQLite review source does not exist")
    where, params = ("", ()) if user_id is None else (" WHERE user_id = ?", (user_id,))
    # URI quoting matters: a filename containing '?' must not change read mode.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        rows = conn.execute(
            "SELECT " + ", ".join(_COLUMNS) +
            f" FROM memory_review_schedule{where} ORDER BY user_id, video_id",
            params,
        ).fetchall()
        seen = set()
        for row in rows:
            video = row["video_id"]
            tenant = row["user_id"]
            if not isinstance(tenant, str) or not tenant.strip() or tenant != tenant.strip():
                raise ValueError("review source has invalid tenant identity")
            if not isinstance(video, str) or not video.strip() or video != video.strip() or (tenant, video) in seen:
                raise ValueError("review source has invalid or duplicate video identity")
            seen.add((tenant, video))
            if not conn.execute(
                "SELECT 1 FROM video_registry WHERE user_id = ? AND video_id = ?",
                (tenant, video),
            ).fetchone():
                raise ValueError("review source lacks exact tenant registry ownership")
            if type(row["review_count"]) is not int or row["review_count"] < 1:
                raise ValueError("review source has an invalid count")
            if row["last_result"] not in {"again", "hard", "good", "easy"}:
                raise ValueError("review source has an invalid outcome")
            try:
                times = [datetime.fromisoformat(row[key]) for key in (
                    "last_reviewed_at", "next_review_at", "updated_at",
                )]
                if any(value.utcoffset() is None for value in times) or times[1] <= times[0]:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("review source has invalid timestamps") from None
        return [tuple(row[column] for column in _COLUMNS) for row in rows]


def preview_review_schedule_migration(settings: Settings | None = None, *, user_id: str | None = None) -> ReviewScheduleMigrationPreview:
    """Validate one read-only snapshot without connecting to Postgres."""
    rows = _source_rows(settings or get_settings(), user_id)
    return ReviewScheduleMigrationPreview(schedules=len(rows), tenants=len({row[0] for row in rows}))


def migrate_review_schedules_to_postgres(
    settings: Settings | None = None, *, user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> ReviewScheduleMigrationReport:
    # Apply revalidates source ownership; a prior preview is not authorization
    # to trust a changed source. Source validation precedes any target access.
    settings = settings or get_settings()
    rows = _source_rows(settings, user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresReviewScheduleStore(factory)
    inserted = 0
    with factory() as target:
        # Lock all owners in stable order before replaying any source rows.
        for owner in sorted({row[0] for row in rows}):
            require_active_tenant(target, user_id=owner)
        for row in rows:
            # Require the registry migration first. Do not retain orphaned
            # derived data merely because a legacy tenant was supplied.
            if not target.execute(
                "SELECT 1 FROM video_registry WHERE user_id = %s AND video_id = %s FOR KEY SHARE",
                row[:2],
            ).fetchone():
                raise ValueError("target lacks exact tenant registry ownership")
            cursor = target.execute(
                "INSERT INTO memory_review_schedule (" + ", ".join(_COLUMNS) + ") "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(user_id, video_id) DO NOTHING",
                row,
            )
            inserted += int(cursor.rowcount)
    return ReviewScheduleMigrationReport(
        schedules_seen=len(rows), schedules_inserted=inserted,
        schedules_skipped_existing=len(rows) - inserted,
    )

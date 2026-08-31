"""Safe, idempotent SQLite -> Postgres migration for video/reflection state.

This helper is intentionally narrow: it migrates only the tenant-scoped
``video_registry`` and ``video_reflection`` tables whose Postgres runtime is
already supported.  The SQLite source is opened read-only and target conflicts
are never overwritten, so re-running a migration cannot clobber newer Postgres
state created after a cutover.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_video_registry import ensure_postgres_video_registry_schema


@dataclass(frozen=True)
class VideoRegistryMigrationPreview:
    videos: int
    reflections: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class VideoRegistryMigrationReport:
    videos_seen: int
    videos_inserted: int
    videos_skipped_existing: int
    reflections_seen: int
    reflections_inserted: int
    reflections_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_video_registry_migration(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
) -> VideoRegistryMigrationPreview:
    """Return count-only source information without contacting Postgres."""
    settings = settings or get_settings()
    with _open_source_read_only(settings) as conn:
        where, params = _tenant_filter(user_id)
        videos = int(
            conn.execute(f"SELECT COUNT(*) FROM video_registry{where}", params).fetchone()[0]
        )
        reflections = int(
            conn.execute(f"SELECT COUNT(*) FROM video_reflection{where}", params).fetchone()[0]
        )
        tenant_where = " WHERE user_id = ?" if user_id is not None else ""
        tenant_params: tuple[Any, ...] = (user_id,) if user_id is not None else ()
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM video_registry{tenant_where}",
                tenant_params,
            ).fetchone()[0]
        )
    return VideoRegistryMigrationPreview(
        videos=videos,
        reflections=reflections,
        tenants=tenants,
    )


def migrate_video_registry_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> VideoRegistryMigrationReport:
    """Insert missing SQLite video/reflection rows into Postgres.

    Existing target rows are deliberately left untouched.  This makes the
    operation safe to retry and prevents an old SQLite snapshot from replacing
    newer target-side counters, timestamps, or reflection choices.
    """
    settings = settings or get_settings()
    factory = connection_factory or get_postgres_connection_factory(settings)
    ensure_postgres_video_registry_schema(factory)

    with _open_source_read_only(settings) as source:
        where, params = _tenant_filter(user_id)
        videos = source.execute(
            "SELECT user_id, video_id, url, title, channel, saved_at, last_viewed, "
            "view_count, search_count, last_searched, helpful_count, not_helpful_count "
            f"FROM video_registry{where} ORDER BY user_id, video_id",
            params,
        ).fetchall()
        reflections = source.execute(
            "SELECT user_id, video_id, save_reason, goal, reflection_note, "
            "recommendations_enabled, preferred_creator_only, allow_other_creators, "
            "difficulty, preferred_style "
            f"FROM video_reflection{where} ORDER BY user_id, video_id",
            params,
        ).fetchall()

    videos_inserted = 0
    reflections_inserted = 0
    with factory() as target:
        for row in videos:
            cur = target.execute(
                """
                INSERT INTO video_registry (
                    user_id, video_id, url, title, channel, saved_at, last_viewed,
                    view_count, search_count, last_searched, helpful_count, not_helpful_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, video_id) DO NOTHING
                """,
                tuple(row),
            )
            videos_inserted += max(int(cur.rowcount or 0), 0)

        for row in reflections:
            values = list(row)
            # psycopg maps Python booleans directly to Postgres BOOLEAN.
            values[5] = bool(values[5])
            values[6] = bool(values[6])
            values[7] = bool(values[7])
            cur = target.execute(
                """
                INSERT INTO video_reflection (
                    user_id, video_id, save_reason, goal, reflection_note,
                    recommendations_enabled, preferred_creator_only, allow_other_creators,
                    difficulty, preferred_style
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, video_id) DO NOTHING
                """,
                tuple(values),
            )
            reflections_inserted += max(int(cur.rowcount or 0), 0)

    return VideoRegistryMigrationReport(
        videos_seen=len(videos),
        videos_inserted=videos_inserted,
        videos_skipped_existing=len(videos) - videos_inserted,
        reflections_seen=len(reflections),
        reflections_inserted=reflections_inserted,
        reflections_skipped_existing=len(reflections) - reflections_inserted,
    )


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _tenant_filter(user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    if user_id is None:
        return "", ()
    return " WHERE user_id = ?", (user_id,)

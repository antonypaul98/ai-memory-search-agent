"""Postgres persistence for tenant-scoped video reflection and usage metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.db.postgres_job_repository import ConnectionFactory
from app.models.reflection import ReflectionDisplay, ReflectionInput, UsageStats
from app.models.user import LOCAL_DEFAULT_USER_ID


def ensure_postgres_video_registry_schema(connection_factory: ConnectionFactory) -> None:
    """Create the video/reflection registry tables idempotently."""
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_registry (
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                saved_at TIMESTAMPTZ NOT NULL,
                last_viewed TIMESTAMPTZ,
                view_count INTEGER NOT NULL DEFAULT 0,
                search_count INTEGER NOT NULL DEFAULT 0,
                last_searched TIMESTAMPTZ,
                helpful_count INTEGER NOT NULL DEFAULT 0,
                not_helpful_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, video_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_reflection (
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                save_reason TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                reflection_note TEXT NOT NULL DEFAULT '',
                recommendations_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                preferred_creator_only BOOLEAN NOT NULL DEFAULT FALSE,
                allow_other_creators BOOLEAN NOT NULL DEFAULT TRUE,
                difficulty TEXT NOT NULL DEFAULT '',
                preferred_style TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, video_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_video_registry_video_id ON video_registry(video_id)"
        )


class PostgresVideoRegistry:
    """Postgres equivalent of the historical SQLite ``VideoRegistry`` contract."""

    def __init__(self, settings: Settings, connection_factory: ConnectionFactory) -> None:
        self._settings = settings
        self._connection_factory = connection_factory

    def upsert_video(
        self,
        *,
        video_id: str,
        url: str,
        title: str,
        channel: str,
        reflection: ReflectionInput | None = None,
        user_id: str = LOCAL_DEFAULT_USER_ID,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO video_registry (user_id, video_id, url, title, channel, saved_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    url = excluded.url,
                    title = excluded.title,
                    channel = excluded.channel
                """,
                (user_id, video_id, url, title, channel, now),
            )
            if reflection:
                conn.execute(
                    """
                    INSERT INTO video_reflection (
                        user_id, video_id, save_reason, goal, reflection_note,
                        recommendations_enabled, preferred_creator_only,
                        allow_other_creators, difficulty, preferred_style
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(user_id, video_id) DO UPDATE SET
                        save_reason = excluded.save_reason,
                        goal = excluded.goal,
                        reflection_note = excluded.reflection_note,
                        recommendations_enabled = excluded.recommendations_enabled,
                        preferred_creator_only = excluded.preferred_creator_only,
                        allow_other_creators = excluded.allow_other_creators,
                        difficulty = excluded.difficulty,
                        preferred_style = excluded.preferred_style
                    """,
                    (
                        user_id,
                        video_id,
                        reflection.save_reason.value,
                        reflection.goal,
                        reflection.reflection_note,
                        reflection.recommendations_enabled,
                        reflection.preferred_creator_only,
                        reflection.allow_other_creators,
                        reflection.difficulty.value,
                        reflection.preferred_style.value,
                    ),
                )

    def is_indexed(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT 1 FROM video_registry WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            ).fetchone()
        return bool(row)

    def delete_video(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                "DELETE FROM video_registry WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            )
            conn.execute(
                "DELETE FROM video_reflection WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            )

    def record_view(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> UsageStats:
        now = datetime.now(timezone.utc)
        with self._connection_factory() as conn:
            conn.execute(
                """
                UPDATE video_registry
                SET view_count = view_count + 1, last_viewed = %s
                WHERE user_id = %s AND video_id = %s
                """,
                (now, user_id, video_id),
            )
        return self.get_usage(video_id, user_id=user_id)

    def record_search(self, video_ids: list[str], *, user_id: str = LOCAL_DEFAULT_USER_ID) -> None:
        if not video_ids:
            return
        now = datetime.now(timezone.utc)
        with self._connection_factory() as conn:
            for video_id in set(video_ids):
                conn.execute(
                    """
                    UPDATE video_registry
                    SET search_count = search_count + 1, last_searched = %s
                    WHERE user_id = %s AND video_id = %s
                    """,
                    (now, user_id, video_id),
                )

    def record_feedback(
        self,
        video_id: str,
        helpful: bool,
        *,
        user_id: str = LOCAL_DEFAULT_USER_ID,
    ) -> UsageStats:
        column = "helpful_count" if helpful else "not_helpful_count"
        with self._connection_factory() as conn:
            conn.execute(
                f"UPDATE video_registry SET {column} = {column} + 1 "
                "WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            )
        return self.get_usage(video_id, user_id=user_id)

    def get_usage(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> UsageStats:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM video_registry WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            ).fetchone()
        if not row:
            return UsageStats()
        return UsageStats(
            saved_at=_iso(row.get("saved_at")),
            last_viewed=_iso(row.get("last_viewed")),
            view_count=row["view_count"],
            search_count=row["search_count"],
            last_searched=_iso(row.get("last_searched")),
            helpful_count=row["helpful_count"],
            not_helpful_count=row["not_helpful_count"],
        )

    def get_reflection(
        self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID
    ) -> ReflectionDisplay:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM video_reflection WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            ).fetchone()
        if not row:
            return ReflectionDisplay()
        goal = row["goal"] or ""
        note = row["reflection_note"] or ""
        return ReflectionDisplay(
            save_reason=row["save_reason"],
            goal=goal,
            reflection_note=note,
            reflection_message=_build_reflection_message(
                save_reason=row["save_reason"], goal=goal, reflection_note=note
            ),
            recommendations_enabled=bool(row["recommendations_enabled"]),
            difficulty=row["difficulty"],
            preferred_style=row["preferred_style"],
        )

    def list_videos(self, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> list[dict[str, Any]]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT r.*, f.save_reason, f.goal, f.reflection_note,
                       f.recommendations_enabled, f.difficulty, f.preferred_style,
                       f.preferred_creator_only, f.allow_other_creators
                FROM video_registry r
                LEFT JOIN video_reflection f
                    ON f.video_id = r.video_id AND f.user_id = r.user_id
                WHERE r.user_id = %s
                ORDER BY r.saved_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [_normalize_row(row) for row in rows]

    def get_video(
        self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID
    ) -> dict[str, Any] | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT r.*, f.save_reason, f.goal, f.reflection_note,
                       f.recommendations_enabled, f.difficulty, f.preferred_style,
                       f.preferred_creator_only, f.allow_other_creators
                FROM video_registry r
                LEFT JOIN video_reflection f
                    ON f.video_id = r.video_id AND f.user_id = r.user_id
                WHERE r.user_id = %s AND r.video_id = %s
                """,
                (user_id, video_id),
            ).fetchone()
        return _normalize_row(row) if row else None

    def other_users_have_video(self, video_id: str, *, excluding_user_id: str) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM video_registry
                WHERE video_id = %s AND user_id != %s
                LIMIT 1
                """,
                (video_id, excluding_user_id),
            ).fetchone()
            if row:
                return True
            row = conn.execute(
                """
                SELECT 1 FROM memory_records
                WHERE external_id = %s AND user_id != %s
                LIMIT 1
                """,
                (video_id, excluding_user_id),
            ).fetchone()
        return bool(row)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _normalize_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in ("saved_at", "last_viewed", "last_searched"):
        if key in result:
            result[key] = _iso(result[key])
    return result


def _build_reflection_message(*, save_reason: str, goal: str, reflection_note: str) -> str:
    if goal and reflection_note:
        return f"You originally saved this for your goal: {goal}. Reflection: {reflection_note}"
    if goal:
        return f"You originally saved this to support your goal: {goal}."
    if reflection_note:
        return f"You saved this because: {reflection_note}"
    if save_reason:
        return f"Saved because: {save_reason.replace('_', ' ')}."
    return ""

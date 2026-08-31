"""
SQLite registry for video-level reflection and usage metadata.

Chroma stores chunk vectors; this registry stores save intent and analytics.
Tenant key is composite (user_id, video_id) as of schema v9.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.schema import migrate
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.reflection import ReflectionInput, ReflectionDisplay, UsageStats

_REGISTRY: dict[str, Any] = {}


def get_video_registry(settings: Settings | None = None) -> Any:
    """Return the registry for the configured production persistence profile.

    The canonical-memory Postgres switch is intentionally shared with this
    legacy registry during P-03 so a production process cannot migrate canonical
    writes while silently leaving reflection/usage writes on local SQLite.
    """
    settings = settings or get_settings()
    if settings.memory_store_backend == "postgres":
        key = f"postgres:{settings.postgres_dsn_env}:{settings.postgres_connect_timeout_sec}"
        if key not in _REGISTRY:
            from app.db.postgres_runtime import get_postgres_connection_factory
            from app.db.postgres_video_registry import (
                PostgresVideoRegistry,
                ensure_postgres_video_registry_schema,
            )

            connection_factory = get_postgres_connection_factory(settings)
            ensure_postgres_video_registry_schema(connection_factory)
            _REGISTRY[key] = PostgresVideoRegistry(settings, connection_factory)
        return _REGISTRY[key]

    key = f"sqlite:{settings.sqlite_path}"
    if key not in _REGISTRY:
        _REGISTRY[key] = VideoRegistry(settings)
    return _REGISTRY[key]


def reset_video_registry_cache() -> None:
    _REGISTRY.clear()


class VideoRegistry:
    """Persist reflection and usage stats per (user_id, video_id)."""

    def __init__(self, settings: Settings) -> None:
        self._path = settings.sqlite_path
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        migrate(settings)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Ensure tables exist for fresh DBs; migrate() owns composite PK rebuild."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS video_registry (
                    user_id TEXT NOT NULL DEFAULT 'local-default',
                    video_id TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL DEFAULT '',
                    saved_at TEXT NOT NULL,
                    last_viewed TEXT,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    search_count INTEGER NOT NULL DEFAULT 0,
                    last_searched TEXT,
                    helpful_count INTEGER NOT NULL DEFAULT 0,
                    not_helpful_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, video_id)
                );

                CREATE TABLE IF NOT EXISTS video_reflection (
                    user_id TEXT NOT NULL DEFAULT 'local-default',
                    video_id TEXT NOT NULL,
                    save_reason TEXT NOT NULL DEFAULT '',
                    goal TEXT NOT NULL DEFAULT '',
                    reflection_note TEXT NOT NULL DEFAULT '',
                    recommendations_enabled INTEGER NOT NULL DEFAULT 0,
                    preferred_creator_only INTEGER NOT NULL DEFAULT 0,
                    allow_other_creators INTEGER NOT NULL DEFAULT 1,
                    difficulty TEXT NOT NULL DEFAULT '',
                    preferred_style TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (user_id, video_id)
                );
                """
            )

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
        now = _utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT video_id FROM video_registry WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE video_registry
                    SET url = ?, title = ?, channel = ?
                    WHERE user_id = ? AND video_id = ?
                    """,
                    (url, title, channel, user_id, video_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO video_registry
                    (user_id, video_id, url, title, channel, saved_at)
                    VALUES (?, ?, ?, ?, ?, ?)
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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        int(reflection.recommendations_enabled),
                        int(reflection.preferred_creator_only),
                        int(reflection.allow_other_creators),
                        reflection.difficulty.value,
                        reflection.preferred_style.value,
                    ),
                )

    def is_indexed(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM video_registry WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            ).fetchone()
            return bool(row)

    def delete_video(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM video_registry WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            )
            conn.execute(
                "DELETE FROM video_reflection WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            )

    def record_view(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> UsageStats:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE video_registry
                SET view_count = view_count + 1, last_viewed = ?
                WHERE user_id = ? AND video_id = ?
                """,
                (now, user_id, video_id),
            )
        return self.get_usage(video_id, user_id=user_id)

    def record_search(
        self,
        video_ids: list[str],
        *,
        user_id: str = LOCAL_DEFAULT_USER_ID,
    ) -> None:
        if not video_ids:
            return
        now = _utc_now()
        with self._connect() as conn:
            for video_id in set(video_ids):
                conn.execute(
                    """
                    UPDATE video_registry
                    SET search_count = search_count + 1, last_searched = ?
                    WHERE user_id = ? AND video_id = ?
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
        with self._connect() as conn:
            conn.execute(
                f"UPDATE video_registry SET {column} = {column} + 1 "
                "WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            )
        return self.get_usage(video_id, user_id=user_id)

    def get_usage(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> UsageStats:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM video_registry WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            ).fetchone()
        if not row:
            return UsageStats()
        return UsageStats(
            saved_at=row["saved_at"],
            last_viewed=row["last_viewed"],
            view_count=row["view_count"],
            search_count=row["search_count"],
            last_searched=row["last_searched"],
            helpful_count=row["helpful_count"],
            not_helpful_count=row["not_helpful_count"],
        )

    def get_reflection(
        self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID
    ) -> ReflectionDisplay:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM video_reflection WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            ).fetchone()
        if not row:
            return ReflectionDisplay()
        goal = row["goal"] or ""
        note = row["reflection_note"] or ""
        message = _build_reflection_message(
            save_reason=row["save_reason"],
            goal=goal,
            reflection_note=note,
        )
        return ReflectionDisplay(
            save_reason=row["save_reason"],
            goal=goal,
            reflection_note=note,
            reflection_message=message,
            recommendations_enabled=bool(row["recommendations_enabled"]),
            difficulty=row["difficulty"],
            preferred_style=row["preferred_style"],
        )

    def list_videos(self, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*, f.save_reason, f.goal, f.reflection_note,
                       f.recommendations_enabled, f.difficulty, f.preferred_style,
                       f.preferred_creator_only, f.allow_other_creators
                FROM video_registry r
                LEFT JOIN video_reflection f
                    ON f.video_id = r.video_id AND f.user_id = r.user_id
                WHERE r.user_id = ?
                ORDER BY r.saved_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_video(
        self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT r.*, f.save_reason, f.goal, f.reflection_note,
                       f.recommendations_enabled, f.difficulty, f.preferred_style,
                       f.preferred_creator_only, f.allow_other_creators
                FROM video_registry r
                LEFT JOIN video_reflection f
                    ON f.video_id = r.video_id AND f.user_id = r.user_id
                WHERE r.user_id = ? AND r.video_id = ?
                """,
                (user_id, video_id),
            ).fetchone()
        return dict(row) if row else None

    def other_users_have_video(self, video_id: str, *, excluding_user_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM video_registry
                WHERE video_id = ? AND user_id != ?
                LIMIT 1
                """,
                (video_id, excluding_user_id),
            ).fetchone()
            if row:
                return True
            row = conn.execute(
                """
                SELECT 1 FROM memory_records
                WHERE external_id = ? AND user_id != ?
                LIMIT 1
                """,
                (video_id, excluding_user_id),
            ).fetchone()
            return bool(row)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_reflection_message(
    *,
    save_reason: str,
    goal: str,
    reflection_note: str,
) -> str:
    if goal and reflection_note:
        return (
            f"You originally saved this for your goal: {goal}. "
            f"Reflection: {reflection_note}"
        )
    if goal:
        return f"You originally saved this to support your goal: {goal}."
    if reflection_note:
        return f"You saved this because: {reflection_note}"
    if save_reason:
        return f"Saved because: {save_reason.replace('_', ' ')}."
    return ""

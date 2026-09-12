"""Postgres persistence for Memory Intelligence creator profiles.

This bounded P-03 slice migrates only creator-profile persistence. Intelligence
 events remain on the legacy IntelligenceStore until their own store is
validated.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.db.intelligence_store import new_id, normalize_topic
from app.models.intelligence import CreatorProfile

ConnectionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_creator(row: Any) -> CreatorProfile:
    video_count = max(int(row["video_count"] or 0), 1)
    beginner = int(row["beginner_count"] or 0) / video_count
    advanced = int(row["advanced_count"] or 0) / video_count
    return CreatorProfile(
        creator_id=row["creator_id"],
        name=row["name"],
        normalized_name=row["normalized_name"] or "",
        channel_id=row["channel_id"] or "",
        video_count=int(row["video_count"] or 0),
        topics_covered=json.loads(row["topics_json"] or "[]"),
        average_depth_sec=float(row["avg_duration_sec"] or 0),
        beginner_friendliness=min(1.0, max(0.0, beginner)),
        advanced_coverage=min(1.0, max(0.0, advanced)),
        related_creators=json.loads(row["related_creators_json"] or "[]"),
        view_count=int(row["view_count"] or 0),
        helpful_count=int(row["helpful_count"] or 0),
        evidence=[
            f"{int(row['video_count'] or 0)} saved videos",
            f"avg duration {float(row['avg_duration_sec'] or 0):.0f}s",
        ],
    )


def _merge_ordered(existing: list[str], incoming: list[str], *, limit: int) -> list[str]:
    return list(dict.fromkeys([*existing, *incoming]))[:limit]


class PostgresCreatorProfileStore:
    """Exact-tenant durable storage for derived creator profiles."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS creator_profiles (
                    creator_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    channel_id TEXT NOT NULL DEFAULT '',
                    video_count INTEGER NOT NULL DEFAULT 0,
                    topics_json TEXT NOT NULL DEFAULT '[]',
                    total_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
                    avg_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
                    beginner_count INTEGER NOT NULL DEFAULT 0,
                    advanced_count INTEGER NOT NULL DEFAULT 0,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    helpful_count INTEGER NOT NULL DEFAULT 0,
                    related_creators_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(user_id, normalized_name)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_creator_profiles_user_order ON creator_profiles(user_id, video_count DESC, helpful_count DESC, creator_id ASC)"
            )

    def replace_creator_stats(
        self,
        *,
        user_id: str,
        name: str,
        channel_id: str = "",
        topics: list[str],
        video_count: int,
        total_duration_sec: float,
        beginner_count: int,
        advanced_count: int,
        view_count: int = 0,
        helpful_count: int = 0,
        related_creators: list[str] | None = None,
    ) -> CreatorProfile:
        normalized = normalize_topic(name) or "unknown"
        clean_name = name.strip() or "Unknown"
        topics = list(dict.fromkeys(topics))[:40]
        related = list(dict.fromkeys(related_creators or []))[:20]
        video_count = max(0, int(video_count))
        total_duration_sec = max(0.0, float(total_duration_sec))
        beginner_count = max(0, min(int(beginner_count), video_count))
        advanced_count = max(0, min(int(advanced_count), video_count))
        avg_duration_sec = total_duration_sec / max(video_count, 1)

        with self._connection_factory() as conn:
            existing = conn.execute(
                "SELECT * FROM creator_profiles WHERE user_id = %s AND normalized_name = %s FOR UPDATE",
                (user_id, normalized),
            ).fetchone()
            if existing:
                creator_id = existing["creator_id"]
                channel_id = channel_id or (existing["channel_id"] or "")
                view_count = max(int(existing["view_count"] or 0), int(view_count))
                helpful_count = max(int(existing["helpful_count"] or 0), int(helpful_count))
                related = _merge_ordered(
                    json.loads(existing["related_creators_json"] or "[]"), related, limit=20
                )
                row = conn.execute(
                    """
                    UPDATE creator_profiles SET
                        name = %s, channel_id = %s, video_count = %s,
                        topics_json = %s, total_duration_sec = %s,
                        avg_duration_sec = %s, beginner_count = %s,
                        advanced_count = %s, view_count = %s, helpful_count = %s,
                        related_creators_json = %s, updated_at = %s
                    WHERE creator_id = %s AND user_id = %s
                    RETURNING *
                    """,
                    (
                        clean_name, channel_id, video_count, json.dumps(topics),
                        total_duration_sec, avg_duration_sec, beginner_count,
                        advanced_count, view_count, helpful_count, json.dumps(related),
                        _now(), creator_id, user_id,
                    ),
                ).fetchone()
            else:
                creator_id = new_id("creator")
                row = conn.execute(
                    """
                    INSERT INTO creator_profiles (
                        creator_id, user_id, name, normalized_name, channel_id,
                        video_count, topics_json, total_duration_sec,
                        avg_duration_sec, beginner_count, advanced_count,
                        view_count, helpful_count, related_creators_json, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        creator_id, user_id, clean_name, normalized, channel_id,
                        video_count, json.dumps(topics), total_duration_sec,
                        avg_duration_sec, beginner_count, advanced_count,
                        max(0, int(view_count)), max(0, int(helpful_count)),
                        json.dumps(related), _now(),
                    ),
                ).fetchone()
        return _row_to_creator(row)

    def upsert_creator(
        self,
        *,
        user_id: str,
        name: str,
        channel_id: str = "",
        topics: list[str],
        duration_sec: float,
        beginner: bool = False,
        advanced: bool = False,
        view_count: int = 0,
        helpful_count: int = 0,
        related_creators: list[str] | None = None,
    ) -> CreatorProfile:
        normalized = normalize_topic(name) or "unknown"
        clean_name = name.strip() or "Unknown"
        incoming_topics = list(dict.fromkeys(topics))[:40]
        incoming_related = list(dict.fromkeys(related_creators or []))[:20]
        duration_sec = max(0.0, float(duration_sec or 0))

        with self._connection_factory() as conn:
            existing = conn.execute(
                "SELECT * FROM creator_profiles WHERE user_id = %s AND normalized_name = %s FOR UPDATE",
                (user_id, normalized),
            ).fetchone()
            if existing:
                creator_id = existing["creator_id"]
                merged_topics = _merge_ordered(
                    json.loads(existing["topics_json"] or "[]"), incoming_topics, limit=40
                )
                merged_related = _merge_ordered(
                    json.loads(existing["related_creators_json"] or "[]"),
                    incoming_related,
                    limit=20,
                )
                count = int(existing["video_count"] or 0) + 1
                total = float(existing["total_duration_sec"] or 0) + duration_sec
                row = conn.execute(
                    """
                    UPDATE creator_profiles SET
                        name = %s, channel_id = %s, video_count = %s,
                        topics_json = %s, total_duration_sec = %s,
                        avg_duration_sec = %s, beginner_count = %s,
                        advanced_count = %s, view_count = %s, helpful_count = %s,
                        related_creators_json = %s, updated_at = %s
                    WHERE creator_id = %s AND user_id = %s
                    RETURNING *
                    """,
                    (
                        clean_name, channel_id or (existing["channel_id"] or ""), count,
                        json.dumps(merged_topics), total, total / max(count, 1),
                        int(existing["beginner_count"] or 0) + int(bool(beginner)),
                        int(existing["advanced_count"] or 0) + int(bool(advanced)),
                        max(int(existing["view_count"] or 0), max(0, int(view_count))),
                        max(int(existing["helpful_count"] or 0), max(0, int(helpful_count))),
                        json.dumps(merged_related), _now(), creator_id, user_id,
                    ),
                ).fetchone()
            else:
                creator_id = new_id("creator")
                row = conn.execute(
                    """
                    INSERT INTO creator_profiles (
                        creator_id, user_id, name, normalized_name, channel_id,
                        video_count, topics_json, total_duration_sec,
                        avg_duration_sec, beginner_count, advanced_count,
                        view_count, helpful_count, related_creators_json, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        creator_id, user_id, clean_name, normalized, channel_id, 1,
                        json.dumps(incoming_topics), duration_sec, duration_sec,
                        int(bool(beginner)), int(bool(advanced)), max(0, int(view_count)),
                        max(0, int(helpful_count)), json.dumps(incoming_related), _now(),
                    ),
                ).fetchone()
        return _row_to_creator(row)

    def get_creator(self, creator_id: str, *, user_id: str) -> CreatorProfile | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM creator_profiles WHERE creator_id = %s AND user_id = %s",
                (creator_id, user_id),
            ).fetchone()
        return _row_to_creator(row) if row else None

    def list_creators(self, user_id: str, *, limit: int = 50) -> list[CreatorProfile]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT * FROM creator_profiles
                WHERE user_id = %s
                ORDER BY video_count DESC, helpful_count DESC, creator_id ASC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_creator(row) for row in rows]

    def find_creator_by_name(self, name: str, *, user_id: str) -> CreatorProfile | None:
        normalized = normalize_topic(name) or "unknown"
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM creator_profiles WHERE user_id = %s AND normalized_name = %s",
                (user_id, normalized),
            ).fetchone()
        return _row_to_creator(row) if row else None

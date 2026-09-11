"""Postgres persistence for Memory Intelligence topic profiles and links.

This intentionally migrates only the topic aggregate boundary. Learning edges,
concept capsules, creator profiles, and intelligence events remain owned by the
legacy IntelligenceStore until their own bounded P-03 slices are validated.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.db.intelligence_store import new_id, normalize_topic
from app.models.intelligence import TopicCategory, TopicProfile

ConnectionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresTopicStore:
    """Tenant-scoped durable topic/profile persistence."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_profiles (
                    topic_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    memory_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TIMESTAMPTZ NOT NULL,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    last_updated_at TIMESTAMPTZ NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    UNIQUE(user_id, normalized_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_memory_links (
                    topic_id TEXT NOT NULL REFERENCES topic_profiles(topic_id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    memory_id TEXT,
                    strength DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                    evidence TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(topic_id, video_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_topic_profiles_tenant_updated ON topic_profiles(user_id, last_updated_at DESC, topic_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_topic_links_tenant_video ON topic_memory_links(user_id, video_id, topic_id)"
            )

    def upsert_topic(
        self,
        *,
        user_id: str,
        name: str,
        category: TopicCategory,
        evidence: str,
        video_id: str,
        memory_id: str | None = None,
        strength: float = 1.0,
        summary_hint: str = "",
    ) -> TopicProfile:
        normalized = normalize_topic(name)
        if not normalized:
            raise ValueError("empty topic name")
        now = _now()
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT * FROM topic_profiles
                WHERE user_id = %s AND normalized_name = %s
                """,
                (user_id, normalized),
            ).fetchone()
            if row:
                topic_id = row["topic_id"]
                evidence_list = json.loads(row["evidence_json"] or "[]")
                if evidence and evidence not in evidence_list:
                    evidence_list.append(evidence)
                    evidence_list = evidence_list[-20:]
                summary = row["summary"] or summary_hint
                if summary_hint and not row["summary"]:
                    summary = summary_hint[:500]
                conn.execute(
                    """
                    UPDATE topic_profiles SET
                        last_seen_at = %s,
                        last_updated_at = %s,
                        evidence_json = %s,
                        summary = CASE WHEN summary = '' THEN %s ELSE summary END
                    WHERE topic_id = %s AND user_id = %s
                    """,
                    (now, now, json.dumps(evidence_list), summary, topic_id, user_id),
                )
            else:
                topic_id = new_id("topic")
                conn.execute(
                    """
                    INSERT INTO topic_profiles (
                        topic_id, user_id, name, normalized_name, category, summary,
                        memory_count, first_seen_at, last_seen_at, last_updated_at, evidence_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s)
                    """,
                    (
                        topic_id,
                        user_id,
                        name.strip(),
                        normalized,
                        category.value,
                        summary_hint[:500],
                        now,
                        now,
                        now,
                        json.dumps([evidence] if evidence else []),
                    ),
                )
            conn.execute(
                """
                INSERT INTO topic_memory_links (
                    topic_id, user_id, video_id, memory_id, strength, evidence
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(topic_id, video_id) DO UPDATE SET
                    memory_id = COALESCE(EXCLUDED.memory_id, topic_memory_links.memory_id),
                    strength = GREATEST(topic_memory_links.strength, EXCLUDED.strength),
                    evidence = CASE
                        WHEN length(EXCLUDED.evidence) > length(topic_memory_links.evidence)
                        THEN EXCLUDED.evidence ELSE topic_memory_links.evidence END
                WHERE topic_memory_links.user_id = EXCLUDED.user_id
                """,
                (topic_id, user_id, video_id, memory_id, strength, evidence),
            )
            count_row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM topic_memory_links
                WHERE topic_id = %s AND user_id = %s
                """,
                (topic_id, user_id),
            ).fetchone()
            conn.execute(
                """
                UPDATE topic_profiles SET memory_count = %s
                WHERE topic_id = %s AND user_id = %s
                """,
                (int(count_row["c"]), topic_id, user_id),
            )
        topic = self.get_topic(topic_id, user_id=user_id)
        if topic is None:  # pragma: no cover - transaction invariant
            raise RuntimeError("topic disappeared after upsert")
        return topic

    def get_topic(self, topic_id: str, *, user_id: str) -> TopicProfile | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT * FROM topic_profiles
                WHERE topic_id = %s AND user_id = %s
                """,
                (topic_id, user_id),
            ).fetchone()
            if not row:
                return None
            links = conn.execute(
                """
                SELECT video_id FROM topic_memory_links
                WHERE topic_id = %s AND user_id = %s
                ORDER BY video_id ASC
                """,
                (topic_id, user_id),
            ).fetchall()
        return _row_to_topic(row, [r["video_id"] for r in links])

    def find_topic_by_name(self, name: str, *, user_id: str) -> TopicProfile | None:
        normalized = normalize_topic(name)
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT * FROM topic_profiles
                WHERE user_id = %s AND normalized_name = %s
                """,
                (user_id, normalized),
            ).fetchone()
            if not row:
                row = conn.execute(
                    """
                    SELECT * FROM topic_profiles
                    WHERE user_id = %s AND (
                        normalized_name LIKE %s OR name LIKE %s
                    )
                    ORDER BY memory_count DESC, last_updated_at DESC, topic_id ASC
                    LIMIT 1
                    """,
                    (user_id, f"%{normalized}%", f"%{name}%"),
                ).fetchone()
            if not row:
                return None
            links = conn.execute(
                """
                SELECT video_id FROM topic_memory_links
                WHERE topic_id = %s AND user_id = %s
                ORDER BY video_id ASC
                """,
                (row["topic_id"], user_id),
            ).fetchall()
        return _row_to_topic(row, [r["video_id"] for r in links])

    def list_topics(self, user_id: str, *, limit: int = 50) -> list[TopicProfile]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT * FROM topic_profiles
                WHERE user_id = %s
                ORDER BY memory_count DESC, last_seen_at DESC, topic_id ASC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
            out: list[TopicProfile] = []
            for row in rows:
                links = conn.execute(
                    """
                    SELECT video_id FROM topic_memory_links
                    WHERE topic_id = %s AND user_id = %s
                    ORDER BY video_id ASC
                    """,
                    (row["topic_id"], user_id),
                ).fetchall()
                out.append(_row_to_topic(row, [r["video_id"] for r in links]))
        return out

    def list_for_export(self, *, user_id: str, limit: int = 10_000) -> list[dict[str, Any]]:
        """Return deterministic raw topic rows for exactly one tenant."""
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT * FROM topic_profiles
                WHERE user_id = %s
                ORDER BY last_updated_at DESC, topic_id ASC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def topics_for_video(self, video_id: str, *, user_id: str) -> list[TopicProfile]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT tp.* FROM topic_profiles tp
                JOIN topic_memory_links tl
                  ON tl.topic_id = tp.topic_id AND tl.user_id = tp.user_id
                WHERE tl.user_id = %s AND tl.video_id = %s
                ORDER BY tl.strength DESC, tp.topic_id ASC
                """,
                (user_id, video_id),
            ).fetchall()
        return [_row_to_topic(r, [video_id]) for r in rows]

    def video_ids_for_topic(self, topic_id: str) -> list[str]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT video_id FROM topic_memory_links
                WHERE topic_id = %s
                ORDER BY video_id ASC
                """,
                (topic_id,),
            ).fetchall()
        return [r["video_id"] for r in rows]


def _row_to_topic(row: Any, video_ids: list[str]) -> TopicProfile:
    return TopicProfile(
        topic_id=row["topic_id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        category=TopicCategory(row["category"]),
        summary=row["summary"] or "",
        memory_count=int(row["memory_count"]),
        video_ids=video_ids,
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        evidence=json.loads(row["evidence_json"] or "[]"),
    )

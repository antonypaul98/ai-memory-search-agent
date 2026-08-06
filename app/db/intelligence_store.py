"""SQLite persistence for Memory Intelligence Layer aggregates."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate
from app.models.intelligence import (
    ConceptCapsule,
    CreatorProfile,
    LearningEdge,
    LearningRelation,
    TopicCategory,
    TopicProfile,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_topic(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9+#.\- ]+", " ", name.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class IntelligenceStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    # ── Topics ──────────────────────────────────────────────────────────

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
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM topic_profiles
                WHERE user_id = ? AND normalized_name = ?
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
                        last_seen_at = ?, last_updated_at = ?,
                        evidence_json = ?, summary = COALESCE(NULLIF(summary, ''), ?)
                    WHERE topic_id = ?
                    """,
                    (now, now, json.dumps(evidence_list), summary, topic_id),
                )
            else:
                topic_id = new_id("topic")
                conn.execute(
                    """
                    INSERT INTO topic_profiles (
                        topic_id, user_id, name, normalized_name, category, summary,
                        memory_count, first_seen_at, last_seen_at, last_updated_at, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
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
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_id, video_id) DO UPDATE SET
                    strength = CASE
                        WHEN excluded.strength > topic_memory_links.strength
                        THEN excluded.strength ELSE topic_memory_links.strength END,
                    evidence = CASE
                        WHEN length(excluded.evidence) > length(topic_memory_links.evidence)
                        THEN excluded.evidence ELSE topic_memory_links.evidence END
                """,
                (topic_id, user_id, video_id, memory_id, strength, evidence),
            )
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM topic_memory_links WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()["c"]
            conn.execute(
                "UPDATE topic_profiles SET memory_count = ? WHERE topic_id = ?",
                (count, topic_id),
            )
        return self.get_topic(topic_id, user_id=user_id)  # type: ignore[return-value]

    def get_topic(self, topic_id: str, *, user_id: str) -> TopicProfile | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM topic_profiles WHERE topic_id = ? AND user_id = ?",
                (topic_id, user_id),
            ).fetchone()
            if not row:
                return None
            links = conn.execute(
                "SELECT video_id FROM topic_memory_links WHERE topic_id = ?",
                (topic_id,),
            ).fetchall()
        return _row_to_topic(row, [r["video_id"] for r in links])

    def find_topic_by_name(self, name: str, *, user_id: str) -> TopicProfile | None:
        normalized = normalize_topic(name)
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM topic_profiles
                WHERE user_id = ? AND normalized_name = ?
                """,
                (user_id, normalized),
            ).fetchone()
            if not row:
                # fuzzy contains
                row = conn.execute(
                    """
                    SELECT * FROM topic_profiles
                    WHERE user_id = ? AND (
                        normalized_name LIKE ? OR name LIKE ?
                    )
                    ORDER BY memory_count DESC LIMIT 1
                    """,
                    (user_id, f"%{normalized}%", f"%{name}%"),
                ).fetchone()
            if not row:
                return None
            links = conn.execute(
                "SELECT video_id FROM topic_memory_links WHERE topic_id = ?",
                (row["topic_id"],),
            ).fetchall()
        return _row_to_topic(row, [r["video_id"] for r in links])

    def list_topics(self, user_id: str, *, limit: int = 50) -> list[TopicProfile]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM topic_profiles WHERE user_id = ?
                ORDER BY memory_count DESC, last_seen_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            out: list[TopicProfile] = []
            for row in rows:
                links = conn.execute(
                    "SELECT video_id FROM topic_memory_links WHERE topic_id = ?",
                    (row["topic_id"],),
                ).fetchall()
                out.append(_row_to_topic(row, [r["video_id"] for r in links]))
        return out

    def topics_for_video(self, video_id: str, *, user_id: str) -> list[TopicProfile]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT tp.* FROM topic_profiles tp
                JOIN topic_memory_links tl ON tl.topic_id = tp.topic_id
                WHERE tl.user_id = ? AND tl.video_id = ?
                ORDER BY tl.strength DESC
                """,
                (user_id, video_id),
            ).fetchall()
        return [_row_to_topic(r, [video_id]) for r in rows]

    def video_ids_for_topic(self, topic_id: str) -> list[str]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                "SELECT video_id FROM topic_memory_links WHERE topic_id = ?",
                (topic_id,),
            ).fetchall()
        return [r["video_id"] for r in rows]

    # ── Learning edges ──────────────────────────────────────────────────

    def upsert_edge(
        self,
        *,
        user_id: str,
        source_video_id: str,
        target_video_id: str,
        relation: LearningRelation,
        strength: float,
        evidence: str,
        evidence_refs: list[str] | None = None,
        source_title: str = "",
        target_title: str = "",
    ) -> LearningEdge:
        if source_video_id == target_video_id:
            raise ValueError("self-edge not allowed")
        now = _now()
        edge_id = new_id("edge")
        refs = evidence_refs or []
        with get_connection(self._settings) as conn:
            existing = conn.execute(
                """
                SELECT edge_id FROM learning_edges
                WHERE user_id = ? AND source_video_id = ? AND target_video_id = ?
                  AND relation = ?
                """,
                (user_id, source_video_id, target_video_id, relation.value),
            ).fetchone()
            if existing:
                edge_id = existing["edge_id"]
                conn.execute(
                    """
                    UPDATE learning_edges SET
                        strength = CASE WHEN ? > strength THEN ? ELSE strength END,
                        evidence = ?,
                        evidence_refs_json = ?
                    WHERE edge_id = ?
                    """,
                    (strength, strength, evidence, json.dumps(refs), edge_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO learning_edges (
                        edge_id, user_id, source_video_id, target_video_id, relation,
                        strength, evidence, evidence_refs_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge_id,
                        user_id,
                        source_video_id,
                        target_video_id,
                        relation.value,
                        strength,
                        evidence,
                        json.dumps(refs),
                        now,
                    ),
                )
        return LearningEdge(
            edge_id=edge_id,
            source_video_id=source_video_id,
            target_video_id=target_video_id,
            relation=relation,
            strength=min(1.0, max(0.0, strength)),
            evidence=evidence,
            evidence_refs=refs,
            source_title=source_title,
            target_title=target_title,
        )

    def edges_for_video(self, video_id: str, *, user_id: str, limit: int = 50) -> list[LearningEdge]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM learning_edges
                WHERE user_id = ? AND (source_video_id = ? OR target_video_id = ?)
                ORDER BY strength DESC LIMIT ?
                """,
                (user_id, video_id, video_id, limit),
            ).fetchall()
        return [_row_to_edge(r) for r in rows]

    def edges_for_topic_videos(
        self, video_ids: list[str], *, user_id: str, limit: int = 100
    ) -> list[LearningEdge]:
        if not video_ids:
            return []
        placeholders = ",".join("?" * len(video_ids))
        params: list[Any] = [user_id, *video_ids, *video_ids, limit]
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM learning_edges
                WHERE user_id = ?
                  AND source_video_id IN ({placeholders})
                  AND target_video_id IN ({placeholders})
                ORDER BY strength DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [_row_to_edge(r) for r in rows]

    def count_edges(self, user_id: str) -> int:
        with get_connection(self._settings) as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM learning_edges WHERE user_id = ?",
                    (user_id,),
                ).fetchone()["c"]
            )

    # ── Concept capsules ────────────────────────────────────────────────

    def upsert_concept_capsule(
        self,
        *,
        user_id: str,
        name: str,
        summary: str,
        topic_ids: list[str],
        video_ids: list[str],
        creators: list[str],
        progress_completed: int | None = None,
    ) -> ConceptCapsule:
        normalized = normalize_topic(name)
        now = _now()
        total = len(video_ids)
        completed = progress_completed if progress_completed is not None else total
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT capsule_id FROM concept_capsules
                WHERE user_id = ? AND normalized_name = ?
                """,
                (user_id, normalized),
            ).fetchone()
            if row:
                capsule_id = row["capsule_id"]
                conn.execute(
                    """
                    UPDATE concept_capsules SET
                        name = ?, summary = ?, topic_ids_json = ?,
                        memory_video_ids_json = ?, creator_names_json = ?,
                        progress_total = ?, progress_completed = ?, updated_at = ?
                    WHERE capsule_id = ?
                    """,
                    (
                        name.strip(),
                        summary[:2000],
                        json.dumps(topic_ids),
                        json.dumps(video_ids),
                        json.dumps(creators),
                        total,
                        completed,
                        now,
                        capsule_id,
                    ),
                )
            else:
                capsule_id = new_id("ccap")
                conn.execute(
                    """
                    INSERT INTO concept_capsules (
                        capsule_id, user_id, name, normalized_name, summary,
                        topic_ids_json, memory_video_ids_json, creator_names_json,
                        progress_total, progress_completed, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capsule_id,
                        user_id,
                        name.strip(),
                        normalized,
                        summary[:2000],
                        json.dumps(topic_ids),
                        json.dumps(video_ids),
                        json.dumps(creators),
                        total,
                        completed,
                        now,
                    ),
                )
        return self.get_concept_capsule(capsule_id, user_id=user_id)  # type: ignore[return-value]

    def get_concept_capsule(self, capsule_id: str, *, user_id: str) -> ConceptCapsule | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM concept_capsules WHERE capsule_id = ? AND user_id = ?",
                (capsule_id, user_id),
            ).fetchone()
        return _row_to_capsule(row) if row else None

    def list_concept_capsules(self, user_id: str, *, limit: int = 50) -> list[ConceptCapsule]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM concept_capsules WHERE user_id = ?
                ORDER BY progress_total DESC, updated_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_capsule(r) for r in rows]

    # ── Creators ────────────────────────────────────────────────────────

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
        """Idempotent creator profile write (full replace of aggregate counters)."""
        normalized = normalize_topic(name) or "unknown"
        now = _now()
        avg = total_duration_sec / max(video_count, 1)
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT creator_id, view_count, helpful_count, related_creators_json
                FROM creator_profiles
                WHERE user_id = ? AND normalized_name = ?
                """,
                (user_id, normalized),
            ).fetchone()
            if row:
                creator_id = row["creator_id"]
                views = max(int(row["view_count"]), view_count)
                helpful = max(int(row["helpful_count"]), helpful_count)
                related = list(
                    dict.fromkeys(
                        [
                            *json.loads(row["related_creators_json"] or "[]"),
                            *(related_creators or []),
                        ]
                    )
                )[:20]
                conn.execute(
                    """
                    UPDATE creator_profiles SET
                        name = ?, channel_id = COALESCE(NULLIF(?, ''), channel_id),
                        video_count = ?, topics_json = ?,
                        total_duration_sec = ?, avg_duration_sec = ?,
                        beginner_count = ?, advanced_count = ?,
                        view_count = ?, helpful_count = ?,
                        related_creators_json = ?, updated_at = ?
                    WHERE creator_id = ?
                    """,
                    (
                        name.strip() or "Unknown",
                        channel_id,
                        video_count,
                        json.dumps(topics[:40]),
                        total_duration_sec,
                        avg,
                        beginner_count,
                        advanced_count,
                        views,
                        helpful,
                        json.dumps(related),
                        now,
                        creator_id,
                    ),
                )
            else:
                creator_id = new_id("creator")
                conn.execute(
                    """
                    INSERT INTO creator_profiles (
                        creator_id, user_id, name, normalized_name, channel_id,
                        video_count, topics_json, total_duration_sec, avg_duration_sec,
                        beginner_count, advanced_count, view_count, helpful_count,
                        related_creators_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        creator_id,
                        user_id,
                        name.strip() or "Unknown",
                        normalized,
                        channel_id,
                        video_count,
                        json.dumps(topics[:40]),
                        total_duration_sec,
                        avg,
                        beginner_count,
                        advanced_count,
                        view_count,
                        helpful_count,
                        json.dumps(related_creators or []),
                        now,
                    ),
                )
        return self.get_creator(creator_id, user_id=user_id)  # type: ignore[return-value]

    def upsert_creator(
        self,
        *,
        user_id: str,
        name: str,
        channel_id: str = "",
        topics: list[str],
        duration_sec: float | None,
        beginner: bool = False,
        advanced: bool = False,
        view_count: int = 0,
        helpful_count: int = 0,
        related_creators: list[str] | None = None,
    ) -> CreatorProfile:
        normalized = normalize_topic(name) or "unknown"
        now = _now()
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM creator_profiles
                WHERE user_id = ? AND normalized_name = ?
                """,
                (user_id, normalized),
            ).fetchone()
            if row:
                creator_id = row["creator_id"]
                existing_topics = json.loads(row["topics_json"] or "[]")
                merged = list(dict.fromkeys([*existing_topics, *topics]))[:40]
                video_count = int(row["video_count"]) + 1
                total_dur = float(row["total_duration_sec"]) + float(duration_sec or 0)
                beg = int(row["beginner_count"]) + (1 if beginner else 0)
                adv = int(row["advanced_count"]) + (1 if advanced else 0)
                views = max(int(row["view_count"]), view_count)
                helpful = max(int(row["helpful_count"]), helpful_count)
                related = list(
                    dict.fromkeys(
                        [
                            *json.loads(row["related_creators_json"] or "[]"),
                            *(related_creators or []),
                        ]
                    )
                )[:20]
                conn.execute(
                    """
                    UPDATE creator_profiles SET
                        channel_id = COALESCE(NULLIF(?, ''), channel_id),
                        video_count = ?, topics_json = ?,
                        total_duration_sec = ?, avg_duration_sec = ?,
                        beginner_count = ?, advanced_count = ?,
                        view_count = ?, helpful_count = ?,
                        related_creators_json = ?, updated_at = ?
                    WHERE creator_id = ?
                    """,
                    (
                        channel_id,
                        video_count,
                        json.dumps(merged),
                        total_dur,
                        total_dur / max(video_count, 1),
                        beg,
                        adv,
                        views,
                        helpful,
                        json.dumps(related),
                        now,
                        creator_id,
                    ),
                )
            else:
                creator_id = new_id("creator")
                dur = float(duration_sec or 0)
                conn.execute(
                    """
                    INSERT INTO creator_profiles (
                        creator_id, user_id, name, normalized_name, channel_id,
                        video_count, topics_json, total_duration_sec, avg_duration_sec,
                        beginner_count, advanced_count, view_count, helpful_count,
                        related_creators_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        creator_id,
                        user_id,
                        name.strip() or "Unknown",
                        normalized,
                        channel_id,
                        json.dumps(topics[:40]),
                        dur,
                        dur,
                        1 if beginner else 0,
                        1 if advanced else 0,
                        view_count,
                        helpful_count,
                        json.dumps(related_creators or []),
                        now,
                    ),
                )
        return self.get_creator(creator_id, user_id=user_id)  # type: ignore[return-value]

    def get_creator(self, creator_id: str, *, user_id: str) -> CreatorProfile | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM creator_profiles WHERE creator_id = ? AND user_id = ?",
                (creator_id, user_id),
            ).fetchone()
        return _row_to_creator(row) if row else None

    def list_creators(self, user_id: str, *, limit: int = 50) -> list[CreatorProfile]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM creator_profiles WHERE user_id = ?
                ORDER BY video_count DESC, helpful_count DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_creator(r) for r in rows]

    def find_creator_by_name(self, name: str, *, user_id: str) -> CreatorProfile | None:
        normalized = normalize_topic(name)
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM creator_profiles
                WHERE user_id = ? AND normalized_name = ?
                """,
                (user_id, normalized),
            ).fetchone()
        return _row_to_creator(row) if row else None

    # ── Events ──────────────────────────────────────────────────────────

    def record_event(
        self,
        *,
        user_id: str,
        event_type: str,
        topic: str | None = None,
        video_id: str | None = None,
        query: str | None = None,
    ) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO intelligence_events (
                    user_id, event_type, topic, video_id, query, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, event_type, topic, video_id, query, _now()),
            )

    def recent_events(
        self, user_id: str, *, event_type: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        with get_connection(self._settings) as conn:
            if event_type:
                rows = conn.execute(
                    """
                    SELECT * FROM intelligence_events
                    WHERE user_id = ? AND event_type = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (user_id, event_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM intelligence_events
                    WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def save_dates(self, user_id: str) -> list[str]:
        """Distinct UTC dates with save events (also falls back to empty)."""
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT substr(created_at, 1, 10) AS d
                FROM intelligence_events
                WHERE user_id = ? AND event_type = 'save'
                ORDER BY d DESC
                """,
                (user_id,),
            ).fetchall()
        return [r["d"] for r in rows if r["d"]]


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


def _row_to_edge(row: Any) -> LearningEdge:
    return LearningEdge(
        edge_id=row["edge_id"],
        source_video_id=row["source_video_id"],
        target_video_id=row["target_video_id"],
        relation=LearningRelation(row["relation"]),
        strength=float(row["strength"]),
        evidence=row["evidence"] or "",
        evidence_refs=json.loads(row["evidence_refs_json"] or "[]"),
    )


def _row_to_capsule(row: Any) -> ConceptCapsule:
    video_ids = json.loads(row["memory_video_ids_json"] or "[]")
    total = int(row["progress_total"] or 0)
    completed = int(row["progress_completed"] or 0)
    progress = (completed / total) if total else 0.0
    return ConceptCapsule(
        capsule_id=row["capsule_id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        summary=row["summary"] or "",
        key_memories=video_ids[:12],
        related_creators=json.loads(row["creator_names_json"] or "[]"),
        topic_ids=json.loads(row["topic_ids_json"] or "[]"),
        learning_progress=min(1.0, max(0.0, progress)),
        memory_count=len(video_ids),
        updated_at=row["updated_at"],
    )


def _row_to_creator(row: Any) -> CreatorProfile:
    video_count = max(int(row["video_count"]), 1)
    beginner = int(row["beginner_count"]) / video_count
    advanced = int(row["advanced_count"]) / video_count
    topics = json.loads(row["topics_json"] or "[]")
    return CreatorProfile(
        creator_id=row["creator_id"],
        name=row["name"],
        normalized_name=row["normalized_name"] or "",
        channel_id=row["channel_id"] or "",
        video_count=int(row["video_count"]),
        topics_covered=topics,
        average_depth_sec=float(row["avg_duration_sec"] or 0),
        beginner_friendliness=min(1.0, beginner),
        advanced_coverage=min(1.0, advanced),
        related_creators=json.loads(row["related_creators_json"] or "[]"),
        view_count=int(row["view_count"]),
        helpful_count=int(row["helpful_count"]),
        evidence=[
            f"{row['video_count']} saved videos",
            f"avg duration {float(row['avg_duration_sec'] or 0):.0f}s",
        ],
    )

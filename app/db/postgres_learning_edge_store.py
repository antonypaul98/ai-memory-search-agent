"""Postgres persistence for Memory Intelligence learning edges.

This bounded P-03 slice migrates only the learning-edge aggregate. Concept
capsules, creator profiles, and intelligence events remain on the legacy
IntelligenceStore until their own stores are validated.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.db.intelligence_store import new_id
from app.models.intelligence import LearningEdge, LearningRelation

ConnectionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


class PostgresLearningEdgeStore:
    """Exact-tenant durable storage for learning relationships."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_edges (
                    edge_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_video_id TEXT NOT NULL,
                    target_video_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    strength DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                    evidence TEXT NOT NULL DEFAULT '',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(user_id, source_video_id, target_video_id, relation)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_edges_source ON learning_edges(user_id, source_video_id, strength DESC, edge_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_edges_target ON learning_edges(user_id, target_video_id, strength DESC, edge_id)"
            )

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
        refs = evidence_refs or []
        edge_id = new_id("edge")
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                INSERT INTO learning_edges (
                    edge_id, user_id, source_video_id, target_video_id, relation,
                    strength, evidence, evidence_refs_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, source_video_id, target_video_id, relation)
                DO UPDATE SET
                    strength = GREATEST(learning_edges.strength, EXCLUDED.strength),
                    evidence = EXCLUDED.evidence,
                    evidence_refs_json = EXCLUDED.evidence_refs_json
                RETURNING edge_id, strength
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
                    _now(),
                ),
            ).fetchone()
        return LearningEdge(
            edge_id=row["edge_id"],
            source_video_id=source_video_id,
            target_video_id=target_video_id,
            relation=relation,
            strength=min(1.0, max(0.0, float(row["strength"]))),
            evidence=evidence,
            evidence_refs=refs,
            source_title=source_title,
            target_title=target_title,
        )

    def edges_for_video(self, video_id: str, *, user_id: str, limit: int = 50) -> list[LearningEdge]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT * FROM learning_edges
                WHERE user_id = %s AND (source_video_id = %s OR target_video_id = %s)
                ORDER BY strength DESC, edge_id ASC LIMIT %s
                """,
                (user_id, video_id, video_id, limit),
            ).fetchall()
        return [_row_to_edge(row) for row in rows]

    def edges_for_topic_videos(
        self, video_ids: list[str], *, user_id: str, limit: int = 100
    ) -> list[LearningEdge]:
        if not video_ids:
            return []
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT * FROM learning_edges
                WHERE user_id = %s
                  AND source_video_id = ANY(%s)
                  AND target_video_id = ANY(%s)
                ORDER BY strength DESC, edge_id ASC LIMIT %s
                """,
                (user_id, video_ids, video_ids, limit),
            ).fetchall()
        return [_row_to_edge(row) for row in rows]

    def count_edges(self, user_id: str) -> int:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM learning_edges WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        return int(row["c"])

"""Postgres persistence for Memory Intelligence concept capsules.

This bounded P-03 slice migrates only the concept-capsule aggregate. Creator
profiles and intelligence events remain on the legacy IntelligenceStore until
their own stores are validated.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.db.intelligence_store import new_id, normalize_topic
from app.models.intelligence import ConceptCapsule

ConnectionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_capsule(row: Any) -> ConceptCapsule:
    total = int(row["progress_total"] or 0)
    completed = int(row["progress_completed"] or 0)
    progress = min(1.0, max(0.0, completed / max(total, 1))) if total else 0.0
    return ConceptCapsule(
        capsule_id=row["capsule_id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        summary=row["summary"] or "",
        key_memories=json.loads(row["memory_video_ids_json"] or "[]"),
        related_creators=json.loads(row["creator_names_json"] or "[]"),
        topic_ids=json.loads(row["topic_ids_json"] or "[]"),
        learning_progress=progress,
        memory_count=total,
        updated_at=row["updated_at"].isoformat()
        if hasattr(row["updated_at"], "isoformat")
        else str(row["updated_at"]),
    )


class PostgresConceptCapsuleStore:
    """Exact-tenant durable storage for derived concept capsules."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS concept_capsules (
                    capsule_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    topic_ids_json TEXT NOT NULL DEFAULT '[]',
                    memory_video_ids_json TEXT NOT NULL DEFAULT '[]',
                    creator_names_json TEXT NOT NULL DEFAULT '[]',
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_completed INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(user_id, normalized_name)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_concept_capsules_user_order ON concept_capsules(user_id, progress_total DESC, updated_at DESC, capsule_id)"
            )

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
        if not normalized:
            raise ValueError("empty concept capsule name")
        total = len(video_ids)
        completed = progress_completed if progress_completed is not None else total
        completed = max(0, min(completed, total))
        capsule_id = new_id("ccap")
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                INSERT INTO concept_capsules (
                    capsule_id, user_id, name, normalized_name, summary,
                    topic_ids_json, memory_video_ids_json, creator_names_json,
                    progress_total, progress_completed, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, normalized_name) DO UPDATE SET
                    name = EXCLUDED.name,
                    summary = EXCLUDED.summary,
                    topic_ids_json = EXCLUDED.topic_ids_json,
                    memory_video_ids_json = EXCLUDED.memory_video_ids_json,
                    creator_names_json = EXCLUDED.creator_names_json,
                    progress_total = EXCLUDED.progress_total,
                    progress_completed = EXCLUDED.progress_completed,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
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
                    _now(),
                ),
            ).fetchone()
        return _row_to_capsule(row)

    def get_concept_capsule(self, capsule_id: str, *, user_id: str) -> ConceptCapsule | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM concept_capsules WHERE capsule_id = %s AND user_id = %s",
                (capsule_id, user_id),
            ).fetchone()
        return _row_to_capsule(row) if row else None

    def list_concept_capsules(self, user_id: str, *, limit: int = 50) -> list[ConceptCapsule]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT * FROM concept_capsules
                WHERE user_id = %s
                ORDER BY progress_total DESC, updated_at DESC, capsule_id ASC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_capsule(row) for row in rows]

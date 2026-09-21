"""Privacy primitives for Postgres Memory Intelligence data.

This module deliberately owns only the four intelligence-domain tables.  It
fails closed on blank tenant ownership and keeps erasure in one transaction so a
partial intelligence-domain deletion cannot be reported as success.
"""

from __future__ import annotations

from app.db.postgres_privacy_tables import table_exists

import json
from typing import Any, Callable

ConnectionFactory = Callable[[], Any]


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not value:
        return []
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, list) else []


def _tenant(user_id: str) -> str:
    tenant = str(user_id or "").strip()
    if not tenant:
        raise ValueError("user_id is required for intelligence privacy")
    return tenant


def export_user_intelligence(
    connection_factory: ConnectionFactory, *, user_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Export all four Postgres intelligence domains for one exact tenant."""

    tenant = _tenant(user_id)
    with connection_factory() as conn:
        capsules = conn.execute(
            "SELECT * FROM concept_capsules WHERE user_id = %s "
            "ORDER BY updated_at, capsule_id",
            (tenant,),
        ).fetchall()
        creators = conn.execute(
            "SELECT * FROM creator_profiles WHERE user_id = %s "
            "ORDER BY updated_at, creator_id",
            (tenant,),
        ).fetchall()
        edges = conn.execute(
            "SELECT * FROM learning_edges WHERE user_id = %s "
            "ORDER BY created_at, edge_id",
            (tenant,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM intelligence_events WHERE user_id = %s "
            "ORDER BY created_at, id",
            (tenant,),
        ).fetchall()

    return {
        "concept_capsules": [
            {
                "capsule_id": row["capsule_id"],
                "user_id": row["user_id"],
                "name": row["name"],
                "normalized_name": row["normalized_name"],
                "summary": row["summary"],
                "topic_ids": _json_list(row["topic_ids_json"]),
                "memory_video_ids": _json_list(row["memory_video_ids_json"]),
                "creator_names": _json_list(row["creator_names_json"]),
                "progress_total": int(row["progress_total"] or 0),
                "progress_completed": int(row["progress_completed"] or 0),
                "updated_at": _as_text(row["updated_at"]),
            }
            for row in capsules
        ],
        "creator_profiles": [
            {
                "creator_id": row["creator_id"],
                "user_id": row["user_id"],
                "name": row["name"],
                "normalized_name": row["normalized_name"],
                "channel_id": row["channel_id"],
                "video_count": int(row["video_count"] or 0),
                "topics": _json_list(row["topics_json"]),
                "total_duration_sec": float(row["total_duration_sec"] or 0),
                "avg_duration_sec": float(row["avg_duration_sec"] or 0),
                "beginner_count": int(row["beginner_count"] or 0),
                "advanced_count": int(row["advanced_count"] or 0),
                "view_count": int(row["view_count"] or 0),
                "helpful_count": int(row["helpful_count"] or 0),
                "related_creators": _json_list(row["related_creators_json"]),
                "updated_at": _as_text(row["updated_at"]),
            }
            for row in creators
        ],
        "learning_edges": [
            {
                "edge_id": row["edge_id"],
                "user_id": row["user_id"],
                "source_video_id": row["source_video_id"],
                "target_video_id": row["target_video_id"],
                "relation": row["relation"],
                "strength": float(row["strength"]),
                "evidence": row["evidence"],
                "evidence_refs": _json_list(row["evidence_refs_json"]),
                "created_at": _as_text(row["created_at"]),
            }
            for row in edges
        ],
        "intelligence_events": [
            {
                "id": int(row["id"]),
                "user_id": row["user_id"],
                "event_type": row["event_type"],
                "topic": row["topic"],
                "video_id": row["video_id"],
                "query": row["query"],
                "created_at": _as_text(row["created_at"]),
            }
            for row in events
        ],
    }


def delete_user_intelligence(
    connection_factory: ConnectionFactory, *, user_id: str
) -> dict[str, int]:
    """Atomically delete all four intelligence domains for one exact tenant."""

    tenant = _tenant(user_id)
    counts: dict[str, int] = {}
    with connection_factory() as conn:
        for table, key in (
            ("learning_edges", "learning_edges"),
            ("intelligence_events", "intelligence_events"),
            ("concept_capsules", "concept_capsules"),
            ("creator_profiles", "creator_profiles"),
        ):
            if not table_exists(conn, table):
                counts[key] = 0
                continue
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE user_id = %s", (tenant,)
            )
            counts[key] = max(0, int(getattr(cursor, "rowcount", 0) or 0))
    return counts

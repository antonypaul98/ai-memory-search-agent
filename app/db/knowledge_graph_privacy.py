"""Privacy operations for the selected knowledge-graph backend.

Keep graph export/deletion tenant-scoped and backend-aware so privacy flows never
silently fall back to SQLite after a Postgres cutover.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.db.knowledge_graph_store_factory import get_selected_knowledge_graph_store
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not value:
        return []
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, list) else []


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _export_entity(row: Any) -> dict[str, Any]:
    return {
        "entity_id": row["entity_id"],
        "user_id": row["user_id"],
        "entity_type": row["entity_type"],
        "name": row["name"],
        "normalized_name": row["normalized_name"],
        "aliases": _json_list(row["aliases_json"]),
        "metadata": _json_object(row["metadata_json"]),
        "created_at": _as_text(row["created_at"]),
        "updated_at": _as_text(row["updated_at"]),
    }


def _export_relation(row: Any) -> dict[str, Any]:
    metadata = _json_object(row["metadata_json"])
    return {
        "relation_id": row["relation_id"],
        "user_id": row["user_id"],
        "subject_entity_id": row["subject_entity_id"],
        "predicate": row["predicate"],
        "object_entity_id": row["object_entity_id"],
        "memory_id": row["memory_id"],
        "confidence": float(row["confidence"]),
        "metadata": metadata,
        "valid_from": metadata.get("valid_from") or _as_text(row["created_at"]),
        "valid_to": metadata.get("valid_to"),
        "created_at": _as_text(row["created_at"]),
    }


def _export_link(row: Any) -> dict[str, Any]:
    return {
        "memory_id": row["memory_id"],
        "entity_id": row["entity_id"],
        "user_id": row["user_id"],
        "mention_context": row["mention_context"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "confidence": float(row["confidence"]),
    }


def export_user_graph(
    settings: Settings,
    *,
    user_id: str,
    store: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Export the selected backend's complete graph data for one exact tenant."""

    selected = store or get_selected_knowledge_graph_store(settings)
    if isinstance(selected, PostgresKnowledgeGraphStore):
        placeholder = "%s"
        connection_factory = selected._connection_factory
    elif isinstance(selected, KnowledgeGraphStore):
        placeholder = "?"

        def connection_factory():
            from app.db.schema import get_connection

            return get_connection(settings)
    else:
        raise RuntimeError("unsupported selected knowledge-graph privacy backend")

    with connection_factory() as conn:
        entities = conn.execute(
            f"SELECT * FROM kg_entities WHERE user_id = {placeholder} "
            "ORDER BY entity_type, normalized_name, entity_id",
            (user_id,),
        ).fetchall()
        relations = conn.execute(
            f"SELECT * FROM kg_relations WHERE user_id = {placeholder} "
            "ORDER BY created_at, relation_id",
            (user_id,),
        ).fetchall()
        links = conn.execute(
            f"SELECT * FROM kg_memory_entities WHERE user_id = {placeholder} "
            "ORDER BY memory_id, entity_id",
            (user_id,),
        ).fetchall()

    return {
        "entities": [_export_entity(row) for row in entities],
        "relations": [_export_relation(row) for row in relations],
        "memory_entity_links": [_export_link(row) for row in links],
    }


def delete_memory_graph_links(
    settings: Settings,
    *,
    memory_id: str,
    user_id: str,
    store: Any | None = None,
) -> int:
    """Delete only this tenant's graph links for one memory.

    Returns the number of removed links when the backend exposes rowcount.
    Unsupported selected-store types fail closed rather than mutating SQLite.
    """

    selected = store or get_selected_knowledge_graph_store(settings)
    if isinstance(selected, PostgresKnowledgeGraphStore):
        with selected._connection_factory() as conn:
            cursor = conn.execute(
                "DELETE FROM kg_memory_entities WHERE memory_id = %s AND user_id = %s",
                (memory_id, user_id),
            )
            return max(0, int(getattr(cursor, "rowcount", 0) or 0))

    if isinstance(selected, KnowledgeGraphStore):
        from app.db.schema import get_connection

        with get_connection(settings) as conn:
            cursor = conn.execute(
                "DELETE FROM kg_memory_entities WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            return max(0, int(getattr(cursor, "rowcount", 0) or 0))

    raise RuntimeError("unsupported selected knowledge-graph privacy backend")

"""Privacy operations for the selected knowledge-graph backend.

Keep graph deletion tenant-scoped and backend-aware so privacy flows never
silently fall back to SQLite after a Postgres cutover.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.db.knowledge_graph_store_factory import get_selected_knowledge_graph_store
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore


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

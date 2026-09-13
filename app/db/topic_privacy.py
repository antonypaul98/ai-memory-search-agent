"""Backend-aware topic-link privacy deletion for P-03."""

from __future__ import annotations

from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_topic_store import PostgresTopicStore
from app.db.schema import get_connection


def delete_memory_topic_links(
    store: IntelligenceStore | PostgresTopicStore,
    *,
    memory_id: str,
    user_id: str,
) -> int:
    """Delete topic links for one tenant-owned canonical memory.

    Topic persistence follows the selected canonical-memory backend. Unknown
    stores fail closed instead of falling back to the legacy SQLite tables.
    """
    if isinstance(store, IntelligenceStore):
        with get_connection(store._settings) as conn:
            cursor = conn.execute(
                "DELETE FROM topic_memory_links WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            return int(cursor.rowcount)

    if isinstance(store, PostgresTopicStore):
        with store._connection_factory() as conn:
            cursor = conn.execute(
                "DELETE FROM topic_memory_links WHERE memory_id = %s AND user_id = %s",
                (memory_id, user_id),
            )
            return int(cursor.rowcount)

    raise TypeError(f"Unsupported topic store: {type(store).__name__}")

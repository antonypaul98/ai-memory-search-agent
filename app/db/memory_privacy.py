"""Backend-aware canonical-memory privacy deletion for P-03."""

from __future__ import annotations

from app.db.memory_store import MemoryStore
from app.db.postgres_memory_store import PostgresMemoryStore
from app.db.schema import get_connection


def delete_canonical_memory(
    store: MemoryStore | PostgresMemoryStore,
    *,
    memory_id: str,
    user_id: str,
) -> bool:
    """Delete one tenant-owned canonical memory and its audit history atomically.

    The selected canonical-memory store is an explicit boundary: SQLite removes
    tenant-scoped child history before the parent, while Postgres relies on the
    canonical schema's ``ON DELETE CASCADE`` foreign keys. Unknown stores fail
    closed rather than falling back to SQLite.
    """
    if isinstance(store, MemoryStore):
        with get_connection(store._settings) as conn:
            owned = conn.execute(
                "SELECT 1 FROM memory_records WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            ).fetchone()
            if owned is None:
                return False
            conn.execute(
                "DELETE FROM memory_trust_history WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM memory_versions WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM memory_lifecycle_events WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM memory_records WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
        return True

    if isinstance(store, PostgresMemoryStore):
        with store._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_records WHERE memory_id = %s AND user_id = %s",
                (memory_id, user_id),
            )
            return bool(cursor.rowcount)

    raise TypeError(f"Unsupported canonical memory store: {type(store).__name__}")

"""Durable production account-erasure write fence.

The marker intentionally survives tenant-data deletion. Producers must consult it
before creating or executing new work so an erasure request cannot race with
already-dispatched work and recreate tenant data.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from typing import Any, Callable

ConnectionFactory = Callable[[], Any]


class AccountErasureFence:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS account_erasure_fences (
                    user_id TEXT PRIMARY KEY,
                    fenced_at TEXT NOT NULL
                )
                """
            )

    def fence(self, *, user_id: str) -> None:
        owner = str(user_id or "").strip()
        if not owner:
            raise ValueError("user_id is required")
        fenced_at = datetime.now(timezone.utc).isoformat()
        with self._connection_factory() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(730031, hashtext(%s))", (owner,))
            conn.execute(
                """
                INSERT INTO account_erasure_fences (user_id, fenced_at)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (owner, fenced_at),
            )

    def is_fenced(self, *, user_id: str) -> bool:
        owner = str(user_id or "").strip()
        if not owner:
            raise ValueError("user_id is required")
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT 1 FROM account_erasure_fences WHERE user_id=%s",
                (owner,),
            ).fetchone()
        return row is not None

    def require_active(self, *, user_id: str) -> None:
        if self.is_fenced(user_id=user_id):
            raise PermissionError("account erasure is in progress or completed")


def require_active_tenant(conn, *, user_id: str) -> None:
    """Serialize a write transaction with the irreversible erasure fence.

    Every writer holds a shared transaction lock until commit; fencing takes the
    exclusive equivalent. A check followed by an unlocked write is insufficient.
    The marker table may be absent only before the first erasure in this schema.
    Writers still lock in that case, so concurrent first-time fencing drains them.
    """
    if not isinstance(user_id, str) or not user_id.strip() or user_id != user_id.strip():
        raise ValueError("user_id is required")
    conn.execute("SELECT pg_advisory_xact_lock_shared(730031, hashtext(%s))", (user_id,))
    exists = conn.execute(
        "SELECT 1 FROM pg_class WHERE oid = to_regclass('account_erasure_fences')"
    ).fetchone()
    if exists is not None:
        fenced = conn.execute(
            "SELECT 1 FROM account_erasure_fences WHERE user_id=%s", (user_id,)
        ).fetchone()
        if fenced is not None:
            raise PermissionError("account erasure is in progress or completed")


@contextmanager
def active_vector_write(settings, *, user_id: str | None):
    """Hold the same production fence lock until an external vector write ends."""
    from app.db.production_storage_profile import is_complete_postgres_profile
    from app.db.postgres_runtime import get_postgres_connection_factory

    if not is_complete_postgres_profile(settings):
        yield
        return
    with get_postgres_connection_factory(settings)() as conn:
        require_active_tenant(conn, user_id=user_id)
        yield

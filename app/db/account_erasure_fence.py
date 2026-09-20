"""Durable production account-erasure write fence.

The marker intentionally survives tenant-data deletion. Producers must consult it
before creating or executing new work so an erasure request cannot race with
already-dispatched work and recreate tenant data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db.postgres_job_repository import ConnectionFactory


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

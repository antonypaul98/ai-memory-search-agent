"""Postgres persistence for tenant-scoped encrypted OAuth connector tokens."""
from __future__ import annotations

from typing import Any

from app.db.postgres_job_repository import ConnectionFactory


class PostgresOAuthTokenStore:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_oauth_tokens (
                    user_id TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    encrypted_payload BYTEA NOT NULL,
                    scopes_json TEXT NOT NULL DEFAULT '[]',
                    expires_at TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, connector_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_connector_oauth_enabled "
                "ON connector_oauth_tokens(user_id, enabled, connector_id)"
            )

    def put(
        self, *, user_id: str, connector_id: str, encrypted_payload: bytes,
        scopes_json: str, expires_at: str | None, now: str,
    ) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO connector_oauth_tokens (
                    user_id, connector_id, encrypted_payload, scopes_json,
                    expires_at, enabled, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, 1, %s, %s)
                ON CONFLICT(user_id, connector_id) DO UPDATE SET
                    encrypted_payload=EXCLUDED.encrypted_payload,
                    scopes_json=EXCLUDED.scopes_json,
                    expires_at=EXCLUDED.expires_at,
                    enabled=1,
                    updated_at=EXCLUDED.updated_at
                """,
                (user_id, connector_id, encrypted_payload, scopes_json, expires_at, now, now),
            )

    def get(self, *, user_id: str, connector_id: str) -> dict[str, Any] | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT encrypted_payload, scopes_json, expires_at, enabled
                FROM connector_oauth_tokens
                WHERE user_id=%s AND connector_id=%s
                """,
                (user_id, connector_id),
            ).fetchone()
        return dict(row) if row else None

    def revoke(
        self, *, user_id: str, connector_id: str, encrypted_payload: bytes, updated_at: str,
    ) -> bool:
        with self._connection_factory() as conn:
            cur = conn.execute(
                """
                UPDATE connector_oauth_tokens
                SET encrypted_payload=%s, enabled=0, expires_at=NULL, updated_at=%s
                WHERE user_id=%s AND connector_id=%s AND enabled=1
                """,
                (encrypted_payload, updated_at, user_id, connector_id),
            )
        return cur.rowcount > 0

    def delete_for_user(self, *, user_id: str) -> int:
        """Delete all locally persisted OAuth credentials for exactly one tenant."""
        owner = str(user_id or "").strip()
        if not owner:
            raise ValueError("user_id is required")
        with self._connection_factory() as conn:
            cur = conn.execute(
                "DELETE FROM connector_oauth_tokens WHERE user_id=%s",
                (owner,),
            )
        return int(cur.rowcount or 0)

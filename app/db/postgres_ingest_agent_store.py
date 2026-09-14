"""Postgres persistence for tenant-scoped ingest-agent rules and claims."""
from __future__ import annotations

from typing import Any

from app.db.postgres_job_repository import ConnectionFactory


class PostgresIngestAgentStore:
    """Persist deterministic ingest-agent state without changing approval semantics."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_agent_rules (
                    rule_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    match_json TEXT NOT NULL DEFAULT '{}',
                    force_refresh INTEGER NOT NULL DEFAULT 0,
                    approved INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingest_agent_rules_user "
                "ON ingest_agent_rules(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_agent_claims (
                    user_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, rule_id, canonical_hash),
                    FOREIGN KEY(rule_id) REFERENCES ingest_agent_rules(rule_id) ON DELETE CASCADE
                )
                """
            )

    def create_rule(
        self, *, rule_id: str, user_id: str, name: str, connector_id: str,
        match_json: str, force_refresh: bool, created_at: str,
    ) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO ingest_agent_rules (
                    rule_id, user_id, name, connector_id, match_json, force_refresh,
                    approved, enabled, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 0, 0, %s, %s)
                """,
                (
                    rule_id, user_id, name, connector_id, match_json,
                    int(force_refresh), created_at, created_at,
                ),
            )

    def approve_rule(self, *, user_id: str, rule_id: str, updated_at: str) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                UPDATE ingest_agent_rules
                SET approved=1, enabled=1, updated_at=%s
                WHERE rule_id=%s AND user_id=%s
                RETURNING rule_id
                """,
                (updated_at, rule_id, user_id),
            ).fetchone()
        return row is not None

    def disable_rule(self, *, user_id: str, rule_id: str, updated_at: str) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                UPDATE ingest_agent_rules
                SET enabled=0, updated_at=%s
                WHERE rule_id=%s AND user_id=%s
                RETURNING rule_id
                """,
                (updated_at, rule_id, user_id),
            ).fetchone()
        return row is not None

    def get_rule(self, *, user_id: str, rule_id: str) -> dict[str, Any] | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM ingest_agent_rules WHERE rule_id=%s AND user_id=%s",
                (rule_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def claim(self, *, user_id: str, rule_id: str, canonical_hash: str, updated_at: str) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                INSERT INTO ingest_agent_claims (
                    user_id, rule_id, canonical_hash, status, updated_at
                ) VALUES (%s, %s, %s, 'processing', %s)
                ON CONFLICT(user_id, rule_id, canonical_hash) DO NOTHING
                RETURNING canonical_hash
                """,
                (user_id, rule_id, canonical_hash, updated_at),
            ).fetchone()
        return row is not None

    def complete_claim(
        self, *, user_id: str, rule_id: str, canonical_hash: str, updated_at: str,
    ) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                UPDATE ingest_agent_claims
                SET status='completed', updated_at=%s
                WHERE user_id=%s AND rule_id=%s AND canonical_hash=%s
                """,
                (updated_at, user_id, rule_id, canonical_hash),
            )

    def release_claim(self, *, user_id: str, rule_id: str, canonical_hash: str) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                DELETE FROM ingest_agent_claims
                WHERE user_id=%s AND rule_id=%s AND canonical_hash=%s
                """,
                (user_id, rule_id, canonical_hash),
            )

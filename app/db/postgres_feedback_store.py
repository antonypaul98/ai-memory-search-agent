"""Postgres persistence primitives for tenant-scoped answer feedback."""
from __future__ import annotations

from datetime import datetime, timezone

from app.db.postgres_job_repository import ConnectionFactory


class PostgresFeedbackStore:
    """Persist feedback interaction metadata without relational SQLite."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS answer_interactions (
                    interaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    route_id TEXT NOT NULL DEFAULT '',
                    output_budget_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    route_fingerprint TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_answer_interactions_user_time "
                "ON answer_interactions(user_id, created_at DESC)"
            )

    def record_interaction(
        self,
        *,
        interaction_id: str,
        user_id: str,
        task_type: str,
        route_id: str,
        output_budget_tokens: int,
        completion_tokens: int,
        route_fingerprint: str,
    ) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO answer_interactions(
                    interaction_id, user_id, task_type, route_id,
                    output_budget_tokens, completion_tokens, route_fingerprint, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(interaction_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    task_type = EXCLUDED.task_type,
                    route_id = EXCLUDED.route_id,
                    output_budget_tokens = EXCLUDED.output_budget_tokens,
                    completion_tokens = EXCLUDED.completion_tokens,
                    route_fingerprint = EXCLUDED.route_fingerprint,
                    created_at = EXCLUDED.created_at
                """,
                (
                    interaction_id,
                    user_id,
                    task_type,
                    route_id,
                    int(output_budget_tokens),
                    int(completion_tokens),
                    route_fingerprint,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_interaction(self, *, interaction_id: str, user_id: str):
        with self._connection_factory() as conn:
            return conn.execute(
                "SELECT * FROM answer_interactions WHERE interaction_id = %s AND user_id = %s",
                (interaction_id, user_id),
            ).fetchone()

    def interaction_count(self, *, user_id: str) -> int:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM answer_interactions WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        return int(row["n"] or 0)

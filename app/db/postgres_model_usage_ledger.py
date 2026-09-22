"""Postgres persistence for tenant-scoped model route usage accounting."""
from __future__ import annotations

from app.db.account_erasure_fence import require_active_tenant

from datetime import datetime, timezone
from typing import Any

from app.db.postgres_model_usage_privacy import export_user_model_usage, delete_user_model_usage

from app.db.postgres_job_repository import ConnectionFactory


class PostgresModelUsageLedger:
    """Persist provider usage counters without relying on relational SQLite."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_route_usage (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_route_usage_user_route_time "
                "ON model_route_usage(user_id, route_id, created_at)"
            )

    def today(self, *, user_id: str, route_id: str) -> tuple[int, int]:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS requests, COALESCE(SUM(total_tokens), 0) AS tokens
                FROM model_route_usage
                WHERE user_id = %s AND route_id = %s AND LEFT(created_at, 10) = %s
                """,
                (user_id, route_id, day),
            ).fetchone()
        return int(row["requests"] or 0), int(row["tokens"] or 0)

    def record(
        self,
        *,
        user_id: str,
        route_id: str,
        provider_id: str,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        created_at: str | None = None,
    ) -> None:
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        with self._connection_factory() as conn:
            require_active_tenant(conn, user_id=user_id)
            conn.execute(
                """
                INSERT INTO model_route_usage(
                    user_id, route_id, provider_id, model_id,
                    prompt_tokens, completion_tokens, total_tokens, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    route_id,
                    provider_id,
                    model_id,
                    int(prompt_tokens),
                    int(completion_tokens),
                    int(total_tokens),
                    timestamp,
                ),
            )

    def export_user_data(self, *, user_id: str) -> list[dict[str, Any]]:
        return export_user_model_usage(self._connection_factory, user_id=user_id)

    def delete_user_data(self, *, user_id: str) -> int:
        return delete_user_model_usage(self._connection_factory, user_id=user_id)

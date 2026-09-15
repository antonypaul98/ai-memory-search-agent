"""Tenant-scoped privacy primitives for Postgres model usage accounting."""
from __future__ import annotations

from typing import Any

from app.db.postgres_job_repository import ConnectionFactory


def export_user_model_usage(
    connection_factory: ConnectionFactory,
    *,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return one tenant's model-route usage in deterministic order."""

    if not str(user_id).strip():
        raise ValueError("user_id is required")

    with connection_factory() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, route_id, provider_id, model_id,
                   prompt_tokens, completion_tokens, total_tokens, created_at
            FROM model_route_usage
            WHERE user_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_user_model_usage(
    connection_factory: ConnectionFactory,
    *,
    user_id: str,
) -> int:
    """Delete one exact tenant's model-route usage without touching neighbors."""

    if not str(user_id).strip():
        raise ValueError("user_id is required")

    with connection_factory() as conn:
        result = conn.execute(
            "DELETE FROM model_route_usage WHERE user_id = %s",
            (user_id,),
        )
    return max(0, int(getattr(result, "rowcount", 0) or 0))

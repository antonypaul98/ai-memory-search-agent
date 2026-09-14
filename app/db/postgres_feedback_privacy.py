"""Privacy deletion primitives for tenant-owned Postgres feedback data."""
from __future__ import annotations

from app.db.postgres_job_repository import ConnectionFactory


def delete_user_feedback_data(
    connection_factory: ConnectionFactory,
    *,
    user_id: str,
) -> dict[str, int]:
    """Delete one tenant's feedback-domain records without touching neighbors.

    The four relations are removed in a single connection/transaction scope and
    every statement carries the exact ``user_id`` predicate.  The interaction
    rows are deleted last so dependent feedback/reward rows disappear first if
    foreign-key constraints are added later.
    """

    if not str(user_id).strip():
        raise ValueError("user_id is required")

    counts: dict[str, int] = {}
    with connection_factory() as conn:
        for key, table in (
            ("feedback", "answer_feedback"),
            ("credit_ledger", "feedback_credit_ledger"),
            ("output_preferences", "output_preferences"),
            ("interactions", "answer_interactions"),
        ):
            result = conn.execute(
                f"DELETE FROM {table} WHERE user_id = %s",
                (user_id,),
            )
            counts[key] = max(0, int(getattr(result, "rowcount", 0) or 0))
    return counts

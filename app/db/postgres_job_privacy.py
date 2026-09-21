"""Exact-tenant background-job erasure for confirmed account deletion."""
from __future__ import annotations

from typing import Any, Callable


class PostgresJobPrivacyStore:
    """Remove one tenant's persisted jobs after the account write fence is durable."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def delete_for_user(self, *, user_id: str) -> dict[str, int]:
        owner = str(user_id or "").strip()
        if not owner:
            raise ValueError("user_id is required")
        with self._connection_factory() as conn:
            counts: dict[str, int] = {}
            for key, table in (("leases", "job_item_leases"), ("events", "job_events")):
                cursor = conn.execute(
                    f"""DELETE FROM {table} child USING background_jobs parent
                        WHERE child.job_id = parent.job_id AND parent.user_id = %s""",
                    (owner,),
                )
                counts[key] = max(0, int(cursor.rowcount or 0))
            cursor = conn.execute(
                """DELETE FROM job_items child USING background_jobs parent
                   WHERE child.job_id = parent.job_id AND parent.user_id = %s""",
                (owner,),
            )
            counts["items"] = max(0, int(cursor.rowcount or 0))
            cursor = conn.execute("DELETE FROM background_jobs WHERE user_id = %s", (owner,))
            counts["jobs"] = max(0, int(cursor.rowcount or 0))
            return counts

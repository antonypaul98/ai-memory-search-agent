"""Compatibility boundary for the legacy local SQLite YouTube store.

Postgres operational metrics are tenant-explicit. SQLite remains the local/self-host
backend, but callers selected through the shared factory should use the same method
shape so runtime services can preserve tenant identity without backend conditionals.
"""

from __future__ import annotations

from typing import Any

from app.db.schema import get_connection
from app.db.youtube_memory_store import YouTubeMemoryStore
from app.services.sources.youtube_connector import CONNECTOR_ID


class SQLiteYouTubeMemoryStore(YouTubeMemoryStore):
    """Legacy SQLite store accepting tenant-explicit selected-store calls."""

    def bump_metric(
        self,
        key: str,
        amount: float = 1.0,
        *,
        user_id: str | None = None,
        as_average: bool = False,
    ) -> None:
        # The legacy SQLite metrics table is intentionally local/global and does not
        # persist tenant identity. Runtime callers pass user_id explicitly; None stays
        # supported only for inherited legacy internals such as enqueue_retry().
        del user_id
        super().bump_metric(key, amount, as_average=as_average)

    def record_search_latency(self, ms: float, *, user_id: str | None = None) -> None:
        self.bump_metric("average_search_latency_ms", ms, user_id=user_id, as_average=True)

    def claim_due_retries(self, *, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Claim only retries owned by the requested tenant."""
        from app.db.youtube_memory_store import _utc_now

        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM connector_retry_queue
                WHERE user_id = ? AND connector_id = ? AND dead_lettered = 0
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, id ASC LIMIT ?
                """,
                (user_id, CONNECTOR_ID, _utc_now(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_retry(self, *, user_id: str, retry_id: int) -> bool:
        """Delete a successful retry only when it belongs to the exact tenant."""
        with get_connection(self._settings) as conn:
            cursor = conn.execute(
                """
                DELETE FROM connector_retry_queue
                WHERE id = ? AND user_id = ? AND connector_id = ?
                """,
                (retry_id, user_id, CONNECTOR_ID),
            )
            return bool(cursor.rowcount)

    def diagnostics(self, *, user_id: str):
        # SQLite is the legacy local/self-host backend and its metric table is global.
        # Accept the selected-store tenant-explicit signature without pretending those
        # historical counters are tenant-isolated. Postgres is the production target.
        del user_id
        return super().diagnostics()

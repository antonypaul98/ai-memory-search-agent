"""Compatibility boundary for the legacy local SQLite YouTube store.

Postgres operational metrics are tenant-explicit. SQLite remains the local/self-host
backend, but callers selected through the shared factory should use the same method
shape so runtime services can preserve tenant identity without backend conditionals.
"""

from __future__ import annotations

from app.db.youtube_memory_store import YouTubeMemoryStore


class SQLiteYouTubeMemoryStore(YouTubeMemoryStore):
    """Legacy SQLite store accepting tenant-explicit selected-store metric calls."""

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

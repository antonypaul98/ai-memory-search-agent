"""Compatibility boundary for the legacy local SQLite YouTube store.

Postgres operational metrics are tenant-explicit. SQLite remains the local/self-host
backend, but callers selected through the shared factory should use the same method
shape so runtime services can preserve tenant identity without backend conditionals.
"""

from __future__ import annotations

from app.db.youtube_memory_store import YouTubeMemoryStore


class SQLiteYouTubeMemoryStore(YouTubeMemoryStore):
    """Legacy SQLite store with the tenant-explicit selected-store metric contract."""

    def bump_metric(
        self,
        key: str,
        amount: float = 1.0,
        *,
        user_id: str,
        as_average: bool = False,
    ) -> None:
        # The legacy SQLite metrics table is intentionally local/global and does not
        # persist tenant identity. Accepting the explicit tenant keeps callers honest
        # while Postgres remains the required tenant-isolated production backend.
        del user_id
        super().bump_metric(key, amount, as_average=as_average)

    def record_search_latency(self, ms: float, *, user_id: str) -> None:
        self.bump_metric("average_search_latency_ms", ms, user_id=user_id, as_average=True)

"""Selected Postgres YouTube store compatibility surface.

The base Postgres store already owns the complete YouTube persistence boundary.
This selected-store subclass adds the tenant-scoped successful-retry completion
operation required by runtime routing without changing legacy call sites first.
"""

from __future__ import annotations

from app.db.postgres_youtube_memory_store import PostgresYouTubeMemoryStore
from app.services.sources.youtube_connector import CONNECTOR_ID


class SelectedPostgresYouTubeMemoryStore(PostgresYouTubeMemoryStore):
    """Postgres YouTube store with backend-neutral retry completion."""

    def complete_retry(self, *, user_id: str, retry_id: int) -> bool:
        """Delete a completed retry only for the exact tenant and connector."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM youtube_retry_queue
                WHERE id = %s AND user_id = %s AND connector_id = %s
                """,
                (retry_id, user_id, CONNECTOR_ID),
            )
            return bool(cursor.rowcount)

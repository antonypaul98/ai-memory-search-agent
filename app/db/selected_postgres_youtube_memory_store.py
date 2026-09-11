"""Selected Postgres YouTube store compatibility surface.

The base Postgres store already owns the complete YouTube persistence boundary.
This selected-store subclass adds tenant-scoped mutation operations required by
runtime routing without changing legacy call sites first.
"""

from __future__ import annotations

from app.db.postgres_youtube_memory_store import PostgresYouTubeMemoryStore
from app.services.sources.youtube_connector import CONNECTOR_ID


class SelectedPostgresYouTubeMemoryStore(PostgresYouTubeMemoryStore):
    """Postgres YouTube store with backend-neutral tenant-scoped mutations."""

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

    def delete_memory(self, *, user_id: str, video_id: str) -> bool:
        """Delete one YouTube memory only for the exact tenant/video identity."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM youtube_memories WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            )
            return bool(cursor.rowcount)

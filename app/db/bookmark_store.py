"""Tenant-scoped browser bookmark persistence."""

from __future__ import annotations

from app.config import Settings
from app.db.schema import get_connection, migrate


class BookmarkStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        migrate(settings)

    def sync_snapshot(
        self,
        *,
        user_id: str,
        source_browser: str,
        items: list[dict],
        snapshot_complete: bool,
        now: str,
    ) -> None:
        current_ids = {str(item["browser_bookmark_id"]) for item in items}
        with get_connection(self._settings) as conn:
            if snapshot_complete:
                if current_ids:
                    placeholders = ",".join("?" for _ in current_ids)
                    conn.execute(
                        f"""
                        UPDATE browser_bookmarks
                        SET removed_in_browser = 1, sync_status = 'removed', last_synced_at = ?
                        WHERE user_id = ? AND source_browser = ?
                          AND browser_bookmark_id NOT IN ({placeholders})
                        """,
                        (now, user_id, source_browser, *sorted(current_ids)),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE browser_bookmarks
                        SET removed_in_browser = 1, sync_status = 'removed', last_synced_at = ?
                        WHERE user_id = ? AND source_browser = ?
                        """,
                        (now, user_id, source_browser),
                    )

            for item in items:
                conn.execute(
                    """
                    INSERT INTO browser_bookmarks (
                        user_id, browser_bookmark_id, folder_path, url, url_hash, title,
                        sync_status, source_browser, last_synced_at, removed_in_browser
                    ) VALUES (?, ?, ?, ?, ?, ?, 'synced', ?, ?, 0)
                    ON CONFLICT(user_id, browser_bookmark_id) DO UPDATE SET
                        folder_path = excluded.folder_path,
                        url = excluded.url,
                        url_hash = excluded.url_hash,
                        title = excluded.title,
                        sync_status = 'synced',
                        source_browser = excluded.source_browser,
                        last_synced_at = excluded.last_synced_at,
                        removed_in_browser = 0
                    """,
                    (
                        user_id,
                        item["browser_bookmark_id"],
                        item["folder_path"],
                        item["url"],
                        item["url_hash"],
                        item["title"],
                        source_browser,
                        now,
                    ),
                )

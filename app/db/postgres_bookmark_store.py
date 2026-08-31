"""Postgres persistence for tenant-scoped browser bookmarks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ConnectionFactory = Callable[[], Any]


class PostgresBookmarkStore:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_bookmarks (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    browser_bookmark_id TEXT NOT NULL,
                    folder_path TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL,
                    url_hash TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    sync_status TEXT NOT NULL DEFAULT 'synced',
                    source_browser TEXT NOT NULL DEFAULT 'chrome',
                    last_synced_at TIMESTAMPTZ NOT NULL,
                    removed_in_browser BOOLEAN NOT NULL DEFAULT FALSE,
                    UNIQUE(user_id, browser_bookmark_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_browser_bookmarks_tenant_browser ON browser_bookmarks(user_id, source_browser, browser_bookmark_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_browser_bookmarks_tenant_hash ON browser_bookmarks(user_id, url_hash)"
            )

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
        with self._connection_factory() as conn:
            if snapshot_complete:
                if current_ids:
                    placeholders = ",".join("%s" for _ in current_ids)
                    conn.execute(
                        f"""
                        UPDATE browser_bookmarks
                        SET removed_in_browser = TRUE, sync_status = 'removed', last_synced_at = %s
                        WHERE user_id = %s AND source_browser = %s
                          AND browser_bookmark_id NOT IN ({placeholders})
                        """,
                        (now, user_id, source_browser, *sorted(current_ids)),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE browser_bookmarks
                        SET removed_in_browser = TRUE, sync_status = 'removed', last_synced_at = %s
                        WHERE user_id = %s AND source_browser = %s
                        """,
                        (now, user_id, source_browser),
                    )

            for item in items:
                conn.execute(
                    """
                    INSERT INTO browser_bookmarks (
                        user_id, browser_bookmark_id, folder_path, url, url_hash, title,
                        sync_status, source_browser, last_synced_at, removed_in_browser
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'synced', %s, %s, FALSE)
                    ON CONFLICT(user_id, browser_bookmark_id) DO UPDATE SET
                        folder_path = EXCLUDED.folder_path,
                        url = EXCLUDED.url,
                        url_hash = EXCLUDED.url_hash,
                        title = EXCLUDED.title,
                        sync_status = 'synced',
                        source_browser = EXCLUDED.source_browser,
                        last_synced_at = EXCLUDED.last_synced_at,
                        removed_in_browser = FALSE
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

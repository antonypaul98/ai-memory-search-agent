"""Tenant-scoped SQLite registry access for saved video memories.

This module provides the lightweight list/delete path described by F-30. It
uses the existing ``video_registry`` / ``video_reflection`` tables and never
scans Chroma, so callers can inspect or remove registry metadata without
loading vector storage.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.db.schema import migrate
from app.models.user import LOCAL_DEFAULT_USER_ID


@dataclass(frozen=True)
class RegistryItem:
    """A saved item represented by SQLite registry metadata only."""

    video_id: str
    url: str
    title: str
    channel: str
    saved_at: str
    last_viewed: str | None
    view_count: int
    search_count: int
    last_searched: str | None
    helpful_count: int
    not_helpful_count: int


class SQLiteRegistryClient:
    """List and delete tenant-local registry entries without touching Chroma."""

    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._path = settings.sqlite_path
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        migrate(settings)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_items(
        self,
        *,
        user_id: str = LOCAL_DEFAULT_USER_ID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RegistryItem]:
        """Return saved items newest-first for one tenant.

        Pagination is bounded and deterministic. Invalid limits/offsets fail
        early rather than producing surprising SQL behavior.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT video_id, url, title, channel, saved_at, last_viewed,
                       view_count, search_count, last_searched,
                       helpful_count, not_helpful_count
                FROM video_registry
                WHERE user_id = ?
                ORDER BY saved_at DESC, video_id ASC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            ).fetchall()

        return [
            RegistryItem(
                video_id=row["video_id"],
                url=row["url"],
                title=row["title"],
                channel=row["channel"],
                saved_at=row["saved_at"],
                last_viewed=row["last_viewed"],
                view_count=row["view_count"],
                search_count=row["search_count"],
                last_searched=row["last_searched"],
                helpful_count=row["helpful_count"],
                not_helpful_count=row["not_helpful_count"],
            )
            for row in rows
        ]

    def delete_item(
        self,
        video_id: str,
        *,
        user_id: str = LOCAL_DEFAULT_USER_ID,
    ) -> bool:
        """Delete one tenant's registry metadata and reflection atomically.

        This intentionally does not delete vector chunks. F-30 is the SQLite
        registry client; vector deletion remains owned by the memory repository
        so callers cannot accidentally perform a broader destructive action.
        """
        if not video_id:
            raise ValueError("video_id is required")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM video_registry WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            ).fetchone()
            if not existing:
                return False

            conn.execute(
                "DELETE FROM video_reflection WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            )
            conn.execute(
                "DELETE FROM video_registry WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            )
            return True

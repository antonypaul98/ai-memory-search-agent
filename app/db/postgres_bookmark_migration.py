"""Safe, idempotent SQLite to Postgres migration for bookmark state."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_bookmark_store import PostgresBookmarkStore
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class BookmarkMigrationPreview:
    bookmarks: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class BookmarkMigrationReport:
    bookmarks_seen: int
    bookmarks_inserted: int
    bookmarks_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_bookmark_migration(settings: Settings | None = None, *, user_id: str | None = None) -> BookmarkMigrationPreview:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as conn:
        bookmarks = int(conn.execute(f"SELECT COUNT(*) FROM browser_bookmarks{where}", params).fetchone()[0])
        tenants = int(conn.execute(f"SELECT COUNT(DISTINCT user_id) FROM browser_bookmarks{where}", params).fetchone()[0])
    return BookmarkMigrationPreview(bookmarks=bookmarks, tenants=tenants)


def migrate_bookmarks_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> BookmarkMigrationReport:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresBookmarkStore(factory)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as source:
        rows = source.execute(
            "SELECT user_id, browser_bookmark_id, folder_path, url, url_hash, title, sync_status, source_browser, last_synced_at, removed_in_browser "
            f"FROM browser_bookmarks{where} ORDER BY user_id, source_browser, browser_bookmark_id",
            params,
        ).fetchall()
    inserted = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """INSERT INTO browser_bookmarks (
                    user_id, browser_bookmark_id, folder_path, url, url_hash, title,
                    sync_status, source_browser, last_synced_at, removed_in_browser
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, browser_bookmark_id) DO NOTHING""",
                tuple(row),
            )
            inserted += max(int(cur.rowcount or 0), 0)
    return BookmarkMigrationReport(
        bookmarks_seen=len(rows),
        bookmarks_inserted=inserted,
        bookmarks_skipped_existing=len(rows) - inserted,
    )


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _normalize_user_id(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    value = user_id.strip()
    if not value:
        raise ValueError("user_id must not be blank")
    return value


def _tenant_filter(user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    return ("", ()) if user_id is None else (" WHERE user_id = ?", (user_id,))

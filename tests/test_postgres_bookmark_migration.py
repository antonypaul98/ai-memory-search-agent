from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_bookmark_migration import migrate_bookmarks_to_postgres, preview_bookmark_migration


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.keys: set[tuple[str, str]] = set()
        self.inserted: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else None
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into browser_bookmarks"):
            key = (values[0], values[1])
            if key in self.keys:
                return _Cursor(0)
            self.keys.add(key)
            self.inserted.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE browser_bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            browser_bookmark_id TEXT NOT NULL,
            folder_path TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL,
            url_hash TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            sync_status TEXT NOT NULL DEFAULT 'synced',
            source_browser TEXT NOT NULL DEFAULT 'chrome',
            last_synced_at TEXT NOT NULL,
            removed_in_browser INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, browser_bookmark_id)
        );
        """)
        conn.executemany(
            "INSERT INTO browser_bookmarks (user_id,browser_bookmark_id,folder_path,url,url_hash,title,sync_status,source_browser,last_synced_at,removed_in_browser) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("bob", "b2", "Work", "https://b", "hb", "B", "removed", "chrome", "2026-01-02T00:00:00+00:00", 1),
                ("alice", "a1", "", "https://a", "ha", "A", "synced", "chrome", "2026-01-01T00:00:00+00:00", 0),
            ],
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    assert preview_bookmark_migration(settings).to_dict() == {"bookmarks": 2, "tenants": 2}
    assert preview_bookmark_migration(settings, user_id="alice").to_dict() == {"bookmarks": 1, "tenants": 1}


def test_migration_is_read_only_deterministic_and_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_bookmarks_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_bookmarks_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {"bookmarks_seen": 2, "bookmarks_inserted": 2, "bookmarks_skipped_existing": 0}
    assert second.to_dict() == {"bookmarks_seen": 2, "bookmarks_inserted": 0, "bookmarks_skipped_existing": 2}
    assert [(row[0], row[1]) for row in target.inserted] == [("alice", "a1"), ("bob", "b2")]
    assert target.inserted[1][6:] == ("removed", "chrome", "2026-01-02T00:00:00+00:00", 1)


def test_blank_tenant_fails_closed(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_bookmark_migration(settings, user_id=" ")


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))
    with pytest.raises(FileNotFoundError):
        preview_bookmark_migration(settings)
    assert not path.exists()

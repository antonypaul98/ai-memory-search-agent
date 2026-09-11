from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import Settings
from app.db.bookmark_store import BookmarkStore
from app.db.postgres_bookmark_store import PostgresBookmarkStore
from app.services import privacy_service as privacy_module
from app.services.privacy_service import PrivacyService


class _Cursor:
    def __init__(self, *, rows=None, row=None):
        self._rows = list(rows or [])
        self._row = row

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class _PgConnection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        packed = tuple(params) if params is not None else None
        self.calls.append((normalized, packed))
        if normalized.startswith("SELECT * FROM browser_bookmarks"):
            return _Cursor(rows=[{"id": 7, "browser_bookmark_id": "bookmark-a", "user_id": "tenant-a"}])
        return _Cursor()


class _PgFactory:
    def __init__(self):
        self.connection = _PgConnection()

    def __call__(self):
        return self.connection


def test_postgres_bookmark_export_is_exact_tenant_scoped_and_bounded():
    factory = _PgFactory()
    store = PostgresBookmarkStore.__new__(PostgresBookmarkStore)
    store._connection_factory = factory

    rows = store.list_for_user(user_id="tenant-a", limit=25)

    assert rows == [{"id": 7, "browser_bookmark_id": "bookmark-a", "user_id": "tenant-a"}]
    assert factory.connection.calls == [
        (
            "SELECT * FROM browser_bookmarks WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            ("tenant-a", 25),
        )
    ]


def test_sqlite_bookmark_export_is_exact_tenant_scoped_and_deterministic(tmp_path):
    path = tmp_path / "bookmarks.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE browser_bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                browser_bookmark_id TEXT NOT NULL,
                folder_path TEXT NOT NULL,
                url TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                sync_status TEXT NOT NULL,
                source_browser TEXT NOT NULL,
                last_synced_at TEXT NOT NULL,
                removed_in_browser INTEGER NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO browser_bookmarks (
                user_id, browser_bookmark_id, folder_path, url, url_hash, title,
                sync_status, source_browser, last_synced_at, removed_in_browser
            ) VALUES (?, ?, '', ?, ?, ?, 'synced', 'chrome', ?, 0)
            """,
            [
                ("tenant-a", "a-1", "https://a1", "h1", "A1", "2026-02-01"),
                ("tenant-b", "b-1", "https://b1", "hb", "B1", "2026-03-01"),
                ("tenant-a", "a-2", "https://a2", "h2", "A2", "2026-02-02"),
            ],
        )

    store = BookmarkStore.__new__(BookmarkStore)
    store._settings = Settings(sqlite_path=str(path))
    rows = store.list_for_user(user_id="tenant-a", limit=10)

    assert [row["browser_bookmark_id"] for row in rows] == ["a-2", "a-1"]
    assert all(row["user_id"] == "tenant-a" for row in rows)


def test_privacy_export_uses_selected_bookmark_store(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._auth_store = MagicMock()
    service._auth_store.get_user_for_export.return_value = {
        "user_id": "tenant-a",
        "email": "a@example.test",
        "display_name": "A",
        "created_at": "now",
    }
    service._memory_store = MagicMock()
    service._memory_store.list_recent.return_value = []
    service._youtube_store = MagicMock()
    service._youtube_store.list_for_user.return_value = []
    service._capture_store = MagicMock()
    service._capture_store.list_for_user.return_value = []
    service._bookmark_store = MagicMock()
    service._bookmark_store.list_for_user.return_value = [
        {"id": 7, "browser_bookmark_id": "selected-bookmark", "user_id": "tenant-a"}
    ]
    service._registry = MagicMock()
    service._registry.list_videos.return_value = []
    selected_jobs = MagicMock(return_value=[])
    monkeypatch.setattr(privacy_module, "list_jobs_for_user", selected_jobs)

    class _PrivacyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(str(sql).split())
            assert "FROM browser_bookmarks" not in normalized
            assert "FROM users" not in normalized
            return _Cursor(rows=[])

    monkeypatch.setattr(privacy_module, "get_connection", lambda settings: _PrivacyConnection())

    payload = service.export_user_data(user_id="tenant-a")

    service._auth_store.get_user_for_export.assert_called_once_with(user_id="tenant-a")
    service._bookmark_store.list_for_user.assert_called_once_with(user_id="tenant-a", limit=5000)
    selected_jobs.assert_called_once_with(service._settings, user_id="tenant-a", limit=500)
    assert payload["browser_bookmarks"] == [
        {"id": 7, "browser_bookmark_id": "selected-bookmark", "user_id": "tenant-a"}
    ]

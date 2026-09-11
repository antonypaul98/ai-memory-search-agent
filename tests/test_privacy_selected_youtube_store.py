from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import Settings
from app.db.selected_postgres_youtube_memory_store import SelectedPostgresYouTubeMemoryStore
from app.db.sqlite_youtube_memory_store import SQLiteYouTubeMemoryStore
from app.services import privacy_service as privacy_module
from app.services.privacy_service import PrivacyService


class _Cursor:
    def __init__(self, *, rowcount: int = 0, rows=None, row=None):
        self.rowcount = rowcount
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
        if normalized.startswith("DELETE FROM youtube_memories"):
            return _Cursor(rowcount=1)
        return _Cursor()


class _PgFactory:
    def __init__(self):
        self.connection = _PgConnection()

    def __call__(self):
        return self.connection


def test_sqlite_youtube_delete_is_exact_tenant_scoped(tmp_path):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE youtube_memories (user_id TEXT NOT NULL, video_id TEXT NOT NULL, PRIMARY KEY (user_id, video_id))"
        )
        conn.executemany(
            "INSERT INTO youtube_memories(user_id, video_id) VALUES (?, ?)",
            [("tenant-a", "shared-video"), ("tenant-b", "shared-video")],
        )

    store = SQLiteYouTubeMemoryStore.__new__(SQLiteYouTubeMemoryStore)
    store._settings = Settings(sqlite_path=str(path))

    assert store.delete_memory(user_id="tenant-a", video_id="shared-video") is True
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM youtube_memories WHERE user_id = ? AND video_id = ?",
            ("tenant-a", "shared-video"),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM youtube_memories WHERE user_id = ? AND video_id = ?",
            ("tenant-b", "shared-video"),
        ).fetchone()[0] == 1


def test_postgres_youtube_delete_carries_exact_tenant_identity():
    factory = _PgFactory()
    store = SelectedPostgresYouTubeMemoryStore.__new__(SelectedPostgresYouTubeMemoryStore)
    store._connect = factory

    assert store.delete_memory(user_id="tenant-a", video_id="shared-video") is True
    assert factory.connection.calls == [
        (
            "DELETE FROM youtube_memories WHERE user_id = %s AND video_id = %s",
            ("tenant-a", "shared-video"),
        )
    ]


def test_privacy_export_uses_selected_youtube_store(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._memory_store = MagicMock()
    service._memory_store.list_recent.return_value = []
    youtube_memory = MagicMock()
    youtube_memory.model_dump.return_value = {
        "user_id": "tenant-a",
        "video_id": "video-a",
        "title": "Selected-store row",
    }
    service._youtube_store = MagicMock()
    service._youtube_store.list_for_user.return_value = [youtube_memory]
    service._capture_store = MagicMock()
    service._capture_store.list_for_user.return_value = []
    service._registry = MagicMock()
    service._registry.list_videos.return_value = []

    class _PrivacyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(str(sql).split())
            if normalized.startswith("SELECT user_id, email"):
                return _Cursor(row={"user_id": "tenant-a", "email": "a@example.test", "display_name": "A", "created_at": "now"})
            return _Cursor(rows=[])

    monkeypatch.setattr(privacy_module, "get_connection", lambda settings: _PrivacyConnection())

    payload = service.export_user_data(user_id="tenant-a")

    service._youtube_store.list_for_user.assert_called_once_with("tenant-a", limit=10_000)
    service._capture_store.list_for_user.assert_called_once_with(user_id="tenant-a", limit=2000)
    assert payload["youtube_memories"] == [
        {"user_id": "tenant-a", "video_id": "video-a", "title": "Selected-store row"}
    ]


def test_non_youtube_privacy_delete_does_not_touch_youtube_store(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._memory_store = MagicMock()
    service._memory_store.get.return_value = SimpleNamespace(
        memory_id="memory-a", external_id="doc-a", source_type="pdf"
    )
    service._repo = MagicMock()
    service._registry = MagicMock()
    service._registry.other_users_have_video.return_value = True
    service._fts = MagicMock()
    service._hstore = MagicMock()
    service._content_url_index = MagicMock()
    service._youtube_store = MagicMock()
    service._delete_sqlite_memory_rows = MagicMock()
    monkeypatch.setattr(privacy_module, "bump_index_version", MagicMock())

    service.delete_memory(memory_id="memory-a", user_id="tenant-a")

    service._youtube_store.delete_memory.assert_not_called()

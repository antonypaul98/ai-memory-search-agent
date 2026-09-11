from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.db.capture_store import CaptureStore
from app.db.postgres_capture_store import PostgresCaptureStore
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
        if normalized.startswith("SELECT * FROM captures"):
            return _Cursor(rows=[{"capture_id": "capture-a", "user_id": "tenant-a"}])
        return _Cursor()


class _PgFactory:
    def __init__(self):
        self.connection = _PgConnection()

    def __call__(self):
        return self.connection


def test_postgres_capture_export_is_exact_tenant_scoped_and_deterministic():
    factory = _PgFactory()
    store = PostgresCaptureStore.__new__(PostgresCaptureStore)
    store._connection_factory = factory

    rows = store.list_for_user(user_id="tenant-a", limit=25)

    assert rows == [{"capture_id": "capture-a", "user_id": "tenant-a"}]
    assert factory.connection.calls == [
        (
            "SELECT * FROM captures WHERE user_id = %s ORDER BY created_at DESC, capture_id ASC LIMIT %s",
            ("tenant-a", 25),
        )
    ]


def test_sqlite_capture_export_is_exact_tenant_scoped(tmp_path):
    import sqlite3

    path = tmp_path / "captures.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE captures (
                capture_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL,
                job_id TEXT,
                stage TEXT NOT NULL,
                stage_detail TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO captures (
                capture_id, user_id, url, url_hash, title, source_type, status,
                job_id, stage, stage_detail, payload_json, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("a-2", "tenant-a", "https://a2", "h2", "A2", "web", "done", None, "done", "done", "{}", None, "2026-02-02", "2026-02-02"),
                ("a-1", "tenant-a", "https://a1", "h1", "A1", "web", "done", None, "done", "done", "{}", None, "2026-02-01", "2026-02-01"),
                ("b-1", "tenant-b", "https://b1", "hb", "B1", "web", "done", None, "done", "done", "{}", None, "2026-03-01", "2026-03-01"),
            ],
        )

    store = CaptureStore.__new__(CaptureStore)
    store._settings = SimpleNamespace(sqlite_path=str(path))
    monkey_settings = store._settings

    # Use the real schema helper's connection contract without running migration.
    from app.config import Settings

    store._settings = Settings(sqlite_path=str(path))
    rows = store.list_for_user(user_id="tenant-a", limit=10)

    assert [row["capture_id"] for row in rows] == ["a-2", "a-1"]
    assert all(row["user_id"] == "tenant-a" for row in rows)


def test_privacy_export_uses_selected_capture_store(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._memory_store = MagicMock()
    service._memory_store.list_recent.return_value = []
    service._youtube_store = MagicMock()
    service._youtube_store.list_for_user.return_value = []
    service._capture_store = MagicMock()
    service._capture_store.list_for_user.return_value = [
        {"capture_id": "selected-capture", "user_id": "tenant-a"}
    ]
    service._registry = MagicMock()
    service._registry.list_videos.return_value = []

    class _PrivacyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(str(sql).split())
            assert "FROM captures" not in normalized
            if normalized.startswith("SELECT user_id, email"):
                return _Cursor(
                    row={
                        "user_id": "tenant-a",
                        "email": "a@example.test",
                        "display_name": "A",
                        "created_at": "now",
                    }
                )
            return _Cursor(rows=[])

    monkeypatch.setattr(privacy_module, "get_connection", lambda settings: _PrivacyConnection())

    payload = service.export_user_data(user_id="tenant-a")

    service._capture_store.list_for_user.assert_called_once_with(user_id="tenant-a", limit=2000)
    assert payload["captures"] == [
        {"capture_id": "selected-capture", "user_id": "tenant-a"}
    ]

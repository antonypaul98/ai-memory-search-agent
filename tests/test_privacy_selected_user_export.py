from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import Settings
from app.db.postgres_auth_store import PostgresAuthStore
from app.services import privacy_service as privacy_module
from app.services.privacy_service import PrivacyService


class _Cursor:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = list(rows or [])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


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
        return _Cursor(
            row={
                "user_id": "tenant-a",
                "email": "a@example.test",
                "display_name": "A",
                "created_at": "2026-09-11T10:00:00+00:00",
            }
        )


class _PgFactory:
    def __init__(self):
        self.connection = _PgConnection()

    def __call__(self):
        return self.connection


def test_postgres_user_export_is_exact_tenant_scoped_and_excludes_secrets():
    factory = _PgFactory()
    store = PostgresAuthStore(Settings(auth_store_backend="postgres"), factory)

    row = store.get_user_for_export(user_id="tenant-a")

    assert row == {
        "user_id": "tenant-a",
        "email": "a@example.test",
        "display_name": "A",
        "created_at": "2026-09-11T10:00:00+00:00",
    }
    assert "password_hash" not in row
    assert factory.connection.calls == [
        (
            "SELECT user_id, email, display_name, created_at FROM users WHERE user_id = %s",
            ("tenant-a",),
        )
    ]


def test_privacy_export_routes_user_through_selected_auth_store(monkeypatch):
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
    service._bookmark_store.list_for_user.return_value = []
    service._registry = MagicMock()
    service._registry.list_videos.return_value = []
    monkeypatch.setattr(privacy_module, "list_jobs_for_user", MagicMock(return_value=[]))

    class _PrivacyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(str(sql).split())
            assert "FROM users" not in normalized
            assert normalized.startswith("SELECT * FROM topic_profiles")
            assert tuple(params) == ("tenant-a",)
            return _Cursor(rows=[])

    monkeypatch.setattr(privacy_module, "get_connection", lambda settings: _PrivacyConnection())

    payload = service.export_user_data(user_id="tenant-a")

    service._auth_store.get_user_for_export.assert_called_once_with(user_id="tenant-a")
    assert payload["user"]["user_id"] == "tenant-a"
    assert "password_hash" not in payload["user"]

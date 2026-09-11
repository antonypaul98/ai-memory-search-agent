from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import Settings
from app.db import job_store_factory as job_factory
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
        return _Cursor(
            rows=[
                {
                    "job_id": "job-a",
                    "user_id": "tenant-a",
                    "created_at": "2026-09-11T10:00:00+00:00",
                }
            ]
        )


class _PgFactory:
    def __init__(self):
        self.connection = _PgConnection()

    def __call__(self):
        return self.connection


def test_job_export_follows_postgres_backend_and_is_exact_tenant_scoped(monkeypatch):
    factory = _PgFactory()
    settings = Settings(job_store_backend="postgres")
    monkeypatch.setattr(job_factory, "get_postgres_connection_factory", lambda settings: factory)

    rows = job_factory.list_jobs_for_user(settings, user_id="tenant-a", limit=25)

    assert rows == [
        {
            "job_id": "job-a",
            "user_id": "tenant-a",
            "created_at": "2026-09-11T10:00:00+00:00",
        }
    ]
    assert factory.connection.calls == [
        (
            "SELECT * FROM background_jobs WHERE user_id = %s ORDER BY created_at DESC, job_id LIMIT %s",
            ("tenant-a", 25),
        )
    ]


def test_privacy_export_routes_jobs_without_legacy_sqlite_read(monkeypatch):
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

    selected_jobs = [
        {"job_id": "selected-job", "user_id": "tenant-a", "created_at": "now"}
    ]
    selected_reader = MagicMock(return_value=selected_jobs)
    monkeypatch.setattr(privacy_module, "list_jobs_for_user", selected_reader)

    class _PrivacyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(str(sql).split())
            assert "FROM background_jobs" not in normalized
            assert "FROM users" not in normalized
            return _Cursor(rows=[])

    monkeypatch.setattr(privacy_module, "get_connection", lambda settings: _PrivacyConnection())

    payload = service.export_user_data(user_id="tenant-a")

    service._auth_store.get_user_for_export.assert_called_once_with(user_id="tenant-a")
    selected_reader.assert_called_once_with(service._settings, user_id="tenant-a", limit=500)
    assert payload["jobs"] == selected_jobs

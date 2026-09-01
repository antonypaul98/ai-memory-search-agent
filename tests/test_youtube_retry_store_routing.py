from __future__ import annotations

from types import SimpleNamespace

from app.api.routes import youtube as youtube_routes
from app.config import Settings
from app.db.selected_postgres_youtube_memory_store import SelectedPostgresYouTubeMemoryStore
from app.db.sqlite_youtube_memory_store import SQLiteYouTubeMemoryStore


class FakeCursor:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((" ".join(str(statement).split()), params))
        return FakeCursor()


def test_selected_postgres_retry_completion_is_tenant_scoped():
    statements = []
    store = SelectedPostgresYouTubeMemoryStore(lambda: FakeConnection(statements))
    statements.clear()

    assert store.complete_retry(user_id="tenant-a", retry_id=42) is True

    statement, params = statements[-1]
    assert "DELETE FROM youtube_retry_queue" in statement
    assert "id = %s AND user_id = %s AND connector_id = %s" in statement
    assert params[0:2] == (42, "tenant-a")


def test_selected_sqlite_retry_completion_is_tenant_scoped(monkeypatch):
    statements = []
    store = SQLiteYouTubeMemoryStore.__new__(SQLiteYouTubeMemoryStore)
    store._settings = object()
    monkeypatch.setattr(
        "app.db.sqlite_youtube_memory_store.get_connection",
        lambda settings: FakeConnection(statements),
    )

    assert store.complete_retry(user_id="tenant-b", retry_id=7) is True

    statement, params = statements[-1]
    assert "DELETE FROM connector_retry_queue" in statement
    assert "id = ? AND user_id = ? AND connector_id = ?" in statement
    assert params[0:2] == (7, "tenant-b")


def test_retry_route_uses_tenant_scoped_store_contract(monkeypatch, tmp_path):
    calls = []

    class Store:
        def claim_due_retries(self, *, user_id, limit):
            calls.append(("claim", user_id, limit))
            return [
                {
                    "id": 5,
                    "url": "https://youtube.com/watch?v=abc",
                    "external_id": "abc",
                    "attempt_count": 1,
                }
            ]

        def complete_retry(self, *, user_id, retry_id):
            calls.append(("complete", user_id, retry_id))
            return True

        def enqueue_retry(self, **kwargs):
            raise AssertionError("successful retry must not be re-enqueued")

    class Ingest:
        def __init__(self, *, settings):
            self.settings = settings

        def ingest_single_url(self, url, *, user_id, force_refresh):
            calls.append(("ingest", user_id, force_refresh, url))
            return SimpleNamespace(success=True, error=None)

    monkeypatch.setattr(youtube_routes, "IngestService", Ingest)
    result = youtube_routes.process_retry_queue(
        user=SimpleNamespace(user_id="tenant-a"),
        store=Store(),
        settings=Settings(sqlite_path=str(tmp_path / "memory.db")),
    )

    assert result == {"processed": 1, "succeeded": 1}
    assert calls[0] == ("claim", "tenant-a", 10)
    assert calls[-1] == ("complete", "tenant-a", 5)

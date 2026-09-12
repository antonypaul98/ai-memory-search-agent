from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import Settings
from app.db.content_url_index_store import ContentUrlIndexStore
from app.db.postgres_content_url_index_store import PostgresContentUrlIndexStore
from app.services import privacy_service as privacy_module
from app.services.privacy_service import PrivacyService


def test_sqlite_content_url_delete_is_exact_tenant_scoped(tmp_path):
    store = ContentUrlIndexStore(Settings(sqlite_path=str(tmp_path / "memory.db")))
    for user_id in ("tenant-a", "tenant-b"):
        store.register(
            user_id=user_id,
            url_hash=f"hash-{user_id}",
            canonical_url="https://example.test/shared",
            content_hash="same-content",
            source_type="youtube",
            connector_id="youtube.v1",
            external_id="shared-video",
            memory_id=f"memory-{user_id}",
        )

    assert store.delete_reference(
        user_id="tenant-a", source_type="youtube", external_id="shared-video"
    ) == 1
    assert store.find_by_url_hash(user_id="tenant-a", url_hash="hash-tenant-a") is None
    assert store.find_by_url_hash(user_id="tenant-b", url_hash="hash-tenant-b") is not None


class _Cursor:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount

    def fetchall(self):
        return []


class _Connection:
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
        if normalized.startswith("DELETE FROM content_url_index"):
            return _Cursor(rowcount=1)
        return _Cursor()


class _Factory:
    def __init__(self):
        self.connections = []

    def __call__(self):
        connection = _Connection()
        self.connections.append(connection)
        return connection

    @property
    def calls(self):
        return [call for connection in self.connections for call in connection.calls]


def test_postgres_content_url_delete_carries_full_tenant_identity():
    factory = _Factory()
    store = PostgresContentUrlIndexStore(factory)

    assert store.delete_reference(
        user_id="tenant-a", source_type="youtube", external_id="shared-video"
    ) == 1

    deletes = [call for call in factory.calls if call[0].startswith("DELETE FROM content_url_index")]
    assert deletes == [
        (
            "DELETE FROM content_url_index WHERE user_id = %s AND source_type = %s AND external_id = %s",
            ("tenant-a", "youtube", "shared-video"),
        )
    ]


def test_privacy_delete_routes_content_url_cleanup_through_selected_store(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._memory_store = MagicMock()
    service._memory_store.get.return_value = SimpleNamespace(
        memory_id="memory-a", external_id="shared-video", source_type="youtube"
    )
    service._repo = MagicMock()
    service._registry = MagicMock()
    service._registry.other_users_have_video.return_value = True
    service._fts = MagicMock()
    service._hstore = MagicMock()
    service._content_url_index = MagicMock()
    service._youtube_store = MagicMock()
    service._delete_sqlite_memory_rows = MagicMock()
    monkeypatch.setattr(privacy_module, "delete_memory_graph_links", MagicMock())
    monkeypatch.setattr(privacy_module, "bump_index_version", MagicMock())

    result = service.delete_memory(memory_id="memory-a", user_id="tenant-a")

    assert result["deleted"] is True
    service._content_url_index.delete_reference.assert_called_once_with(
        user_id="tenant-a", source_type="youtube", external_id="shared-video"
    )
    service._youtube_store.delete_memory.assert_called_once_with(
        user_id="tenant-a", video_id="shared-video"
    )
    service._delete_sqlite_memory_rows.assert_called_once_with(
        memory_id="memory-a",
        user_id="tenant-a",
        external_id="shared-video",
        source_type="youtube",
        delete_shared_capsule=False,
    )

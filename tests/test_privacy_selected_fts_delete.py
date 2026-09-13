from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import privacy_service as privacy_module
from app.services.privacy_service import PrivacyService


def test_privacy_service_initializes_fts_through_selected_factory(monkeypatch):
    settings = SimpleNamespace()
    marker = MagicMock()
    selected_fts = MagicMock(return_value=marker)

    monkeypatch.setattr(privacy_module, "migrate", MagicMock())
    monkeypatch.setattr(privacy_module, "is_complete_postgres_profile", MagicMock(return_value=False))
    monkeypatch.setattr(privacy_module, "get_auth_store", MagicMock())
    monkeypatch.setattr(privacy_module, "get_memory_store", MagicMock())
    monkeypatch.setattr(privacy_module, "get_content_url_index_store", MagicMock())
    monkeypatch.setattr(privacy_module, "get_youtube_memory_store", MagicMock())
    monkeypatch.setattr(privacy_module, "get_ingest_artifact_store", MagicMock())
    monkeypatch.setattr(privacy_module, "get_capture_store", MagicMock())
    monkeypatch.setattr(privacy_module, "get_bookmark_store", MagicMock())
    monkeypatch.setattr(privacy_module, "get_topic_store", MagicMock())
    monkeypatch.setattr(privacy_module, "MemoryRepository", MagicMock())
    monkeypatch.setattr(privacy_module, "get_video_registry", MagicMock())
    monkeypatch.setattr(
        privacy_module, "get_fts_index_for_exclusive_delete", selected_fts
    )
    monkeypatch.setattr(privacy_module, "HierarchicalStore", MagicMock())

    service = PrivacyService(settings)

    selected_fts.assert_called_once_with(settings)
    assert service._fts is marker


def test_privacy_delete_passes_exact_tenant_to_selected_fts_and_invalidates_selected_cache(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._memory_store = MagicMock()
    service._memory_store.get.return_value = SimpleNamespace(
        memory_id="memory-a", external_id="doc-a", source_type="pdf"
    )
    service._repo = MagicMock()
    service._registry = MagicMock()
    service._registry.other_users_have_video.return_value = False
    service._fts = MagicMock()
    service._hstore = MagicMock()
    service._artifact_store = MagicMock()
    service._content_url_index = MagicMock()
    service._youtube_store = MagicMock()
    service._topic_store = MagicMock()

    selected_cache = MagicMock()
    cache_factory = MagicMock(return_value=selected_cache)
    monkeypatch.setattr(privacy_module, "SemanticCache", cache_factory)
    monkeypatch.setattr(privacy_module, "delete_capsule_artifact", MagicMock())
    monkeypatch.setattr(privacy_module, "delete_memory_graph_links", MagicMock())
    monkeypatch.setattr(privacy_module, "delete_memory_topic_links", MagicMock())
    monkeypatch.setattr(privacy_module, "delete_canonical_memory", MagicMock(return_value=True))

    service.delete_memory(memory_id="memory-a", user_id="tenant-a")

    service._fts.delete_video.assert_called_once_with("doc-a", user_id="tenant-a")
    service._hstore.delete_video.assert_called_once_with("doc-a")
    cache_factory.assert_called_once_with(service._settings)
    selected_cache.bump_index_version_and_invalidate.assert_called_once_with()

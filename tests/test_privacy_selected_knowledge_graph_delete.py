from __future__ import annotations

import inspect

from app.config import Settings
from app.db.memory_store import MemoryStore, reset_memory_store_cache
from app.db.schema import SCHEMA_VERSION, migrate
from app.models.lifecycle import MemoryLifecycleState
from app.models.video import SourceType
from app.services import privacy_service as privacy_module
from app.services.privacy_service import PrivacyService


def test_privacy_delete_routes_graph_links_through_selected_boundary(tmp_path, monkeypatch):
    settings = Settings(
        sqlite_path=str(tmp_path / "privacy-graph.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        schema_version=SCHEMA_VERSION,
    )
    migrate(settings)
    reset_memory_store_cache()
    store = MemoryStore(settings)
    memory = store.upsert(
        user_id="tenant-a",
        source_type=SourceType.WEB,
        external_id="graph-delete-1",
        canonical_url="https://example.com/graph-delete-1",
        title="Graph delete routing",
        lifecycle_state=MemoryLifecycleState.TRUSTED,
    )

    calls = []

    def _delete_graph_links(selected_settings, *, memory_id, user_id, store=None):
        calls.append((selected_settings, memory_id, user_id, store))
        return 1

    monkeypatch.setattr(privacy_module, "delete_memory_graph_links", _delete_graph_links)

    result = PrivacyService(settings).delete_memory(
        memory_id=memory.memory_id,
        user_id="tenant-a",
    )

    assert result["deleted"] is True
    assert calls == [(settings, memory.memory_id, "tenant-a", None)]
    assert store.get(memory.memory_id, user_id="tenant-a") is None


def test_sqlite_residual_cleanup_no_longer_bypasses_graph_backend():
    source = inspect.getsource(PrivacyService._delete_sqlite_memory_rows)
    assert "kg_memory_entities" not in source

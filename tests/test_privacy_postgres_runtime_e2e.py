"""Selected relational privacy execution; Chroma is a separate storage boundary."""
import os
import sqlite3
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.video import SourceType
from app.services import privacy_service as privacy_module

pytestmark = pytest.mark.skipif(
    not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"), reason="real Postgres DSN required"
)


@pytest.mark.parametrize("shared", [False, True])
def test_selected_privacy_search_delete_is_sqlite_free_and_retryable(monkeypatch, tmp_path, shared):
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "must-not-exist.db"),
        semantic_cache_enabled=False,
    )
    # Only vector storage is isolated. All selected relational stores and privacy
    # helpers execute against the real database, including cache invalidation.
    monkeypatch.setattr(privacy_module, "MemoryRepository", MagicMock())
    monkeypatch.setattr(privacy_module, "HierarchicalStore", MagicMock())

    def reject_sqlite(*args, **kwargs):
        raise AssertionError("relational privacy runtime opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    service = privacy_module.PrivacyService(settings)
    owner = "privacy-runtime-" + uuid4().hex
    other = owner + "-other"
    external_id = "shared-" + uuid4().hex
    memories = {}
    tenants = (owner, other) if shared else (owner,)
    try:
        for tenant in tenants:
            memories[tenant] = service._memory_store.upsert(
                user_id=tenant, source_type=SourceType.PDF, external_id=external_id,
                canonical_url="https://example.com/document.pdf", title="private lexical evidence",
            )
            service._registry.upsert_video(
                user_id=tenant, video_id=external_id, url="https://example.com/document.pdf",
                title="private lexical evidence", channel="",
            )
            service._fts.upsert(
                user_id=tenant, video_id=external_id, level="capsule", doc_id=external_id,
                title="private lexical evidence", body="private lexical evidence",
            )
            service._review_schedule.record_result(
                user_id=tenant, video_id=external_id, result="good",
            )
        exported = service.export_user_data(user_id=owner)
        assert len(exported["review_schedules"]) == 1
        assert exported["review_schedules"][0]["user_id"] == owner
        assert exported["review_schedules"][0]["video_id"] == external_id
        assert service._fts.search("lexical", user_id=owner, video_ids=[external_id])
        assert service._fts.search("lexical", user_id=owner + "-stranger", video_ids=[external_id]) == []

        # A failed lexical delete must retain the canonical record for retry.
        with monkeypatch.context() as patch:
            patch.setattr(service._fts, "delete_video", MagicMock(side_effect=RuntimeError("injected failure")))
            with pytest.raises(RuntimeError, match="injected failure"):
                service.delete_memory(memory_id=memories[owner].memory_id, user_id=owner)
        assert service._memory_store.get(memories[owner].memory_id, user_id=owner)
        assert service._fts.search("lexical", user_id=owner, video_ids=[external_id])

        # Review deletion failures must also preserve ownership and review data
        # for a later successful retry, even after lexical deletion succeeded.
        with monkeypatch.context() as patch:
            patch.setattr(service._review_schedule, "delete", MagicMock(side_effect=RuntimeError("review delete failure")))
            with pytest.raises(RuntimeError, match="review delete failure"):
                service.delete_memory(memory_id=memories[owner].memory_id, user_id=owner)
        assert service._memory_store.get(memories[owner].memory_id, user_id=owner)
        assert service._review_schedule.get(user_id=owner, video_id=external_id)

        with pytest.raises(KeyError):
            service.delete_memory(memory_id=memories[owner].memory_id, user_id=other)
        result = service.delete_memory(memory_id=memories[owner].memory_id, user_id=owner)
        assert result["deleted"] is True
        assert service._memory_store.get(memories[owner].memory_id, user_id=owner) is None
        assert service._fts.search("lexical", user_id=owner, video_ids=[external_id]) == []
        assert service._review_schedule.get(user_id=owner, video_id=external_id) is None
        if shared:
            assert service._memory_store.get(memories[other].memory_id, user_id=other)
            assert service._fts.search("lexical", user_id=other, video_ids=[external_id])
            assert service._review_schedule.get(user_id=other, video_id=external_id)["review_count"] == 1
            service._hstore.delete_video.assert_not_called()
        exported = service.export_user_data(user_id=owner)
        assert not exported["memories"]
        assert not exported["video_registry"]
        assert not exported["review_schedules"]
        assert not (tmp_path / "must-not-exist.db").exists()
    finally:
        for tenant, memory in memories.items():
            if service._memory_store.get(memory.memory_id, user_id=tenant):
                service.delete_memory(memory_id=memory.memory_id, user_id=tenant)

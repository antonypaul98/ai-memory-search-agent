"""Review metadata follows the real local privacy lifecycle and failure boundary."""
from unittest.mock import MagicMock

import pytest

from app.models.video import SourceType
from app.services import privacy_service as privacy_module
from app.services.privacy_service import dump_export_markdown, load_export_markdown


def test_review_privacy_export_delete_and_failure_retry(test_settings, monkeypatch):
    monkeypatch.setattr(privacy_module, "MemoryRepository", MagicMock())
    monkeypatch.setattr(privacy_module, "HierarchicalStore", MagicMock())
    service = privacy_module.PrivacyService(test_settings)
    memories = {}
    for tenant in ("owner", "other"):
        memories[tenant] = service._memory_store.upsert(
            user_id=tenant, source_type=SourceType.PDF, external_id="shared",
            canonical_url="https://example.test/shared.pdf", title="Review fixture",
        )
        service._registry.upsert_video(
            user_id=tenant, video_id="shared", url="https://example.test/shared.pdf",
            title="Review fixture", channel="",
        )
        service._review_schedule.record_result(user_id=tenant, video_id="shared", result="good")
    exported = service.export_user_data(user_id="owner")
    assert len(exported["review_schedules"]) == 1
    assert exported["review_schedules"][0]["user_id"] == "owner"
    assert load_export_markdown(dump_export_markdown(exported))["review_schedules"] == exported["review_schedules"]

    with monkeypatch.context() as patch:
        patch.setattr(service._review_schedule, "delete", MagicMock(side_effect=RuntimeError("review delete failure")))
        with pytest.raises(RuntimeError, match="review delete failure"):
            service.delete_memory(memory_id=memories["owner"].memory_id, user_id="owner")
    assert service._memory_store.get(memories["owner"].memory_id, user_id="owner")
    assert service._review_schedule.get(user_id="owner", video_id="shared")
    with pytest.raises(KeyError):
        service.delete_memory(memory_id=memories["owner"].memory_id, user_id="other")
    result = service.delete_memory(memory_id=memories["owner"].memory_id, user_id="owner")
    assert result["deleted"] is True
    assert service.export_user_data(user_id="owner")["review_schedules"] == []
    assert service._review_schedule.get(user_id="other", video_id="shared")["review_count"] == 1
    assert service._memory_store.get(memories["other"].memory_id, user_id="other")

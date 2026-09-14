"""Focused tests for production tenant-erasure orchestration."""
from __future__ import annotations

import pytest

from app.services import privacy_erasure


class _PrivacyService:
    def __init__(self, result):
        self.result = result
        self.user_ids: list[str] = []

    def delete_all_memories(self, *, user_id: str):
        self.user_ids.append(user_id)
        return self.result


def test_delete_production_user_data_erases_memory_and_feedback(monkeypatch):
    service = _PrivacyService({"deleted_count": 3, "errors": []})
    connection_factory = object()
    calls: list[tuple[object, str]] = []

    monkeypatch.setattr(privacy_erasure, "is_complete_postgres_profile", lambda settings: True)
    monkeypatch.setattr(
        privacy_erasure,
        "get_postgres_connection_factory",
        lambda settings: connection_factory,
    )

    def _delete_feedback(factory, *, user_id: str):
        calls.append((factory, user_id))
        return {"feedback": 2, "credit_ledger": 1, "output_preferences": 1, "interactions": 4}

    monkeypatch.setattr(privacy_erasure, "delete_user_feedback_data", _delete_feedback)

    result = privacy_erasure.delete_production_user_data(
        object(), user_id="tenant-a", privacy_service=service
    )

    assert service.user_ids == ["tenant-a"]
    assert calls == [(connection_factory, "tenant-a")]
    assert result == {
        "deleted": True,
        "memory_deleted_count": 3,
        "memory_errors": [],
        "feedback_deleted": {
            "feedback": 2,
            "credit_ledger": 1,
            "output_preferences": 1,
            "interactions": 4,
        },
    }


def test_delete_production_user_data_reports_partial_memory_failure_but_erases_feedback(monkeypatch):
    service = _PrivacyService({"deleted_count": 1, "errors": ["memory-2: delete failed"]})
    feedback_user_ids: list[str] = []

    monkeypatch.setattr(privacy_erasure, "is_complete_postgres_profile", lambda settings: True)
    monkeypatch.setattr(privacy_erasure, "get_postgres_connection_factory", lambda settings: object())

    def _delete_feedback(factory, *, user_id: str):
        feedback_user_ids.append(user_id)
        return {"feedback": 1, "credit_ledger": 0, "output_preferences": 0, "interactions": 1}

    monkeypatch.setattr(privacy_erasure, "delete_user_feedback_data", _delete_feedback)

    result = privacy_erasure.delete_production_user_data(
        object(), user_id="tenant-a", privacy_service=service
    )

    assert feedback_user_ids == ["tenant-a"]
    assert result["deleted"] is False
    assert result["memory_errors"] == ["memory-2: delete failed"]


def test_delete_production_user_data_fails_closed_before_deletion(monkeypatch):
    service = _PrivacyService({"deleted_count": 0, "errors": []})
    monkeypatch.setattr(privacy_erasure, "is_complete_postgres_profile", lambda settings: False)

    with pytest.raises(RuntimeError, match="complete Postgres profile"):
        privacy_erasure.delete_production_user_data(
            object(), user_id="tenant-a", privacy_service=service
        )
    assert service.user_ids == []

    with pytest.raises(ValueError, match="user_id is required"):
        privacy_erasure.delete_production_user_data(
            object(), user_id="   ", privacy_service=service
        )
    assert service.user_ids == []

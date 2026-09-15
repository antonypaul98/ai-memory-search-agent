"""Focused tests for production tenant-erasure orchestration."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.db.postgres_feedback_store import PostgresFeedbackStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.feedback import FeedbackIssue, FeedbackSubmitRequest
from app.services import privacy_erasure
from app.services.feedback_service import FeedbackService


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
    monkeypatch.setattr(privacy_erasure, "PostgresEventStore", lambda factory:
        SimpleNamespace(delete_user_data=lambda *, user_id: {"events": 0, "subscriptions": 0}))
    monkeypatch.setattr(privacy_erasure, "PostgresModelUsageLedger", lambda factory:
        SimpleNamespace(delete_user_data=lambda *, user_id: 0))

    result = privacy_erasure.delete_production_user_data(
        object(), user_id="tenant-a", privacy_service=service
    )

    assert service.user_ids == ["tenant-a"]
    assert calls == [(connection_factory, "tenant-a")]
    assert result == {
        "deleted": True,
        "memory_deleted_count": 3,
        "memory_errors": [],
        "model_usage_deleted": 0,
        "activity_deleted": {"events": 0, "subscriptions": 0},
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
    monkeypatch.setattr(privacy_erasure, "PostgresEventStore", lambda factory:
        SimpleNamespace(delete_user_data=lambda *, user_id: {"events": 0, "subscriptions": 0}))
    monkeypatch.setattr(privacy_erasure, "PostgresModelUsageLedger", lambda factory:
        SimpleNamespace(delete_user_data=lambda *, user_id: 0))

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


@pytest.fixture
def pg_tenant_erasure(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    sqlite_attempts = []

    def reject_sqlite(*args, **kwargs):
        sqlite_attempts.append(True)
        raise AssertionError("production tenant erasure opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    factory = get_postgres_connection_factory(settings)
    store = PostgresFeedbackStore(factory)
    nonce = uuid4().hex
    owner = f"privacy-erasure-owner-{nonce}"
    other = f"privacy-erasure-other-{nonce}"
    try:
        yield settings, store, factory, owner, other, nonce
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM answer_feedback WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM feedback_credit_ledger WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM output_preferences WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM answer_interactions WHERE user_id IN (%s, %s)", (owner, other))
        assert sqlite_attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_real_postgres_tenant_erasure_is_two_tenant_isolated(pg_tenant_erasure):
    settings, store, _, owner, other, nonce = pg_tenant_erasure
    feedback_service = FeedbackService(settings)

    for user_id, suffix in ((owner, "owner"), (other, "other")):
        interaction_id = f"privacy-erasure-{suffix}-{nonce}"
        feedback_service.record_interaction(
            interaction_id=interaction_id,
            user_id=user_id,
            task_type="general",
            route_id="provider:model",
            output_budget_tokens=320,
            completion_tokens=200,
            route_fingerprint=f"fp-{suffix}",
        )
        response = feedback_service.submit(
            user_id=user_id,
            request=FeedbackSubmitRequest(
                interaction_id=interaction_id,
                rating=4,
                issues=[FeedbackIssue.TOO_LONG],
                comment=f"{suffix} private feedback",
            ),
        )
        assert response.duplicate is False
        assert response.reward_credits > 0
        assert response.preference_updated is True

    memory_service = _PrivacyService({"deleted_count": 0, "errors": []})
    result = privacy_erasure.delete_production_user_data(
        settings,
        user_id=owner,
        privacy_service=memory_service,
    )

    assert memory_service.user_ids == [owner]
    assert result["deleted"] is True
    assert all(count > 0 for count in result["feedback_deleted"].values())

    owner_export = store.export_user_data(user_id=owner)
    other_export = store.export_user_data(user_id=other)
    for collection in ("interactions", "feedback", "credit_ledger", "output_preferences"):
        assert owner_export[collection] == []
        assert other_export[collection]
        assert all(row["user_id"] == other for row in other_export[collection])

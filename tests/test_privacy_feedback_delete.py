"""Privacy erase acceptance for the Postgres feedback domain."""
from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_feedback_store import PostgresFeedbackStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.feedback import FeedbackIssue, FeedbackSubmitRequest
from app.services import privacy_service as privacy_module
from app.services.feedback_service import FeedbackService
from app.services.privacy_service import PrivacyService


class _EmptyMemoryStore:
    def list_recent(self, *, user_id: str, limit: int):
        return []


def _bare_service(settings) -> PrivacyService:
    service = PrivacyService.__new__(PrivacyService)
    service._settings = settings
    service._memory_store = _EmptyMemoryStore()
    return service


def test_production_privacy_erase_deletes_feedback_for_exact_tenant(monkeypatch):
    service = _bare_service(SimpleNamespace())
    factory = object()
    calls = []

    monkeypatch.setattr(privacy_module, "is_complete_postgres_profile", lambda settings: True)
    monkeypatch.setattr(privacy_module, "get_postgres_connection_factory", lambda settings: factory)
    monkeypatch.setattr(
        privacy_module,
        "delete_user_feedback_data",
        lambda connection_factory, *, user_id: calls.append((connection_factory, user_id)) or {},
    )

    result = service.delete_all_memories(user_id="tenant-a")

    assert result == {"deleted_count": 0, "errors": []}
    assert calls == [(factory, "tenant-a")]


def test_production_privacy_erase_surfaces_feedback_delete_failure(monkeypatch):
    service = _bare_service(SimpleNamespace())

    monkeypatch.setattr(privacy_module, "is_complete_postgres_profile", lambda settings: True)
    monkeypatch.setattr(privacy_module, "get_postgres_connection_factory", lambda settings: object())

    def fail_delete(connection_factory, *, user_id: str):
        raise RuntimeError("feedback delete failed")

    monkeypatch.setattr(privacy_module, "delete_user_feedback_data", fail_delete)

    result = service.delete_all_memories(user_id="tenant-a")

    assert result["deleted_count"] == 0
    assert result["errors"] == ["feedback_records: feedback delete failed"]


def test_local_privacy_erase_does_not_touch_postgres_feedback(monkeypatch):
    service = _bare_service(SimpleNamespace())

    monkeypatch.setattr(privacy_module, "is_complete_postgres_profile", lambda settings: False)

    def unexpected(*args, **kwargs):
        raise AssertionError("local privacy erase must not call Postgres feedback deletion")

    monkeypatch.setattr(privacy_module, "delete_user_feedback_data", unexpected)

    assert service.delete_all_memories(user_id="tenant-local") == {
        "deleted_count": 0,
        "errors": [],
    }


@pytest.fixture
def pg_feedback_erase(monkeypatch, tmp_path):
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
        raise AssertionError("production feedback privacy erase opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    factory = get_postgres_connection_factory(settings)
    store = PostgresFeedbackStore(factory)
    nonce = uuid4().hex
    owner = f"privacy-feedback-delete-owner-{nonce}"
    other = f"privacy-feedback-delete-other-{nonce}"
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


def test_real_postgres_broad_privacy_erase_deletes_only_owner_feedback(pg_feedback_erase):
    settings, store, _, owner, other, nonce = pg_feedback_erase
    feedback_service = FeedbackService(settings)

    for user_id, suffix in ((owner, "owner"), (other, "other")):
        interaction_id = f"privacy-delete-{suffix}-{nonce}"
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

    result = _bare_service(settings).delete_all_memories(user_id=owner)
    assert result == {"deleted_count": 0, "errors": []}

    owner_export = store.export_user_data(user_id=owner)
    other_export = store.export_user_data(user_id=other)

    for collection in ("interactions", "feedback", "credit_ledger", "output_preferences"):
        assert owner_export[collection] == []
        assert other_export[collection]
        assert all(row["user_id"] == other for row in other_export[collection])

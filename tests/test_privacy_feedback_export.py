"""Privacy export acceptance for the Postgres feedback domain."""
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


class _Dumpable:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self, *, mode="json"):
        return dict(self._payload)


class _FeedbackExportSpy:
    def __init__(self):
        self.user_ids = []

    def export_user_data(self, *, user_id: str):
        self.user_ids.append(user_id)
        return {
            "interactions": [{"user_id": user_id, "interaction_id": "i-1"}],
            "feedback": [{"user_id": user_id, "id": 1}],
            "credit_ledger": [{"user_id": user_id, "credits": 5}],
            "output_preferences": [{"user_id": user_id, "task_type": "general"}],
        }


def test_privacy_export_wires_feedback_payload_with_exact_tenant(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._memory_store = SimpleNamespace(
        list_recent=lambda *, user_id, limit: [_Dumpable({"memory_id": "m-1", "user_id": user_id})]
    )
    service._youtube_store = SimpleNamespace(list_for_user=lambda user_id, limit: [])
    service._capture_store = SimpleNamespace(list_for_user=lambda *, user_id, limit: [])
    service._bookmark_store = SimpleNamespace(list_for_user=lambda *, user_id, limit: [])
    service._auth_store = SimpleNamespace(get_user_for_export=lambda *, user_id: {"user_id": user_id})
    service._topic_store = SimpleNamespace(list_topics=lambda user_id, limit: [])
    service._registry = SimpleNamespace(list_videos=lambda *, user_id: [])
    service._review_schedule = SimpleNamespace(list_for_user=lambda *, user_id: [])
    feedback = _FeedbackExportSpy()
    service._feedback_store = feedback

    monkeypatch.setattr(privacy_module, "list_jobs_for_user", lambda settings, *, user_id, limit: [])
    monkeypatch.setattr(privacy_module, "export_user_graph", lambda settings, *, user_id: [])

    payload = service.export_user_data(user_id="tenant-a")

    assert feedback.user_ids == ["tenant-a"]
    assert payload["feedback_records"]["interactions"][0]["user_id"] == "tenant-a"
    assert payload["feedback_records"]["feedback"][0]["user_id"] == "tenant-a"
    assert payload["feedback_records"]["credit_ledger"][0]["user_id"] == "tenant-a"
    assert payload["feedback_records"]["output_preferences"][0]["user_id"] == "tenant-a"


def test_local_privacy_export_does_not_invent_feedback_payload(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._memory_store = SimpleNamespace(list_recent=lambda *, user_id, limit: [])
    service._youtube_store = SimpleNamespace(list_for_user=lambda user_id, limit: [])
    service._capture_store = SimpleNamespace(list_for_user=lambda *, user_id, limit: [])
    service._bookmark_store = SimpleNamespace(list_for_user=lambda *, user_id, limit: [])
    service._auth_store = SimpleNamespace(get_user_for_export=lambda *, user_id: {"user_id": user_id})
    service._topic_store = SimpleNamespace(list_topics=lambda user_id, limit: [])
    service._registry = SimpleNamespace(list_videos=lambda *, user_id: [])
    service._review_schedule = SimpleNamespace(list_for_user=lambda *, user_id: [])
    service._feedback_store = None

    monkeypatch.setattr(privacy_module, "list_jobs_for_user", lambda settings, *, user_id, limit: [])
    monkeypatch.setattr(privacy_module, "export_user_graph", lambda settings, *, user_id: [])

    payload = service.export_user_data(user_id="tenant-local")
    assert "feedback_records" not in payload


@pytest.fixture
def pg_feedback_privacy(monkeypatch, tmp_path):
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
        raise AssertionError("production feedback privacy path opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    factory = get_postgres_connection_factory(settings)
    store = PostgresFeedbackStore(factory)
    nonce = uuid4().hex
    owner = f"privacy-feedback-owner-{nonce}"
    other = f"privacy-feedback-other-{nonce}"
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


def test_real_postgres_feedback_export_is_two_tenant_isolated(pg_feedback_privacy):
    settings, store, _, owner, other, nonce = pg_feedback_privacy
    service = FeedbackService(settings)

    for user_id, suffix in ((owner, "owner"), (other, "other")):
        interaction_id = f"privacy-{suffix}-{nonce}"
        service.record_interaction(
            interaction_id=interaction_id,
            user_id=user_id,
            task_type="general",
            route_id="provider:model",
            output_budget_tokens=320,
            completion_tokens=200,
            route_fingerprint=f"fp-{suffix}",
        )
        response = service.submit(
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

    owner_export = store.export_user_data(user_id=owner)
    other_export = store.export_user_data(user_id=other)

    for collection in ("interactions", "feedback", "credit_ledger", "output_preferences"):
        assert owner_export[collection]
        assert other_export[collection]
        assert all(row["user_id"] == owner for row in owner_export[collection])
        assert all(row["user_id"] == other for row in other_export[collection])
        assert not any(row["user_id"] == other for row in owner_export[collection])
        assert not any(row["user_id"] == owner for row in other_export[collection])

"""Real-Postgres acceptance for tenant-scoped feedback persistence."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_feedback_store import PostgresFeedbackStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.feedback import FeedbackIssue, FeedbackSubmitRequest
from app.services.feedback_service import FeedbackService


@pytest.fixture
def pg_feedback_store(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("production feedback path opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    factory = get_postgres_connection_factory(settings)
    store = PostgresFeedbackStore(factory)
    nonce = uuid4().hex
    owner = f"feedback-owner-{nonce}"
    other = f"feedback-other-{nonce}"
    interaction_id = f"ans_{nonce}"
    try:
        yield settings, store, factory, owner, other, interaction_id
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM answer_feedback WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM feedback_credit_ledger WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM output_preferences WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM answer_interactions WHERE user_id IN (%s, %s)", (owner, other))
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_feedback_interaction_round_trip_and_tenant_isolation(pg_feedback_store):
    _, store, _, owner, other, interaction_id = pg_feedback_store
    store.record_interaction(
        interaction_id=interaction_id, user_id=owner, task_type="general",
        route_id="provider:model", output_budget_tokens=320,
        completion_tokens=123, route_fingerprint="fingerprint-a",
    )
    row = store.get_interaction(interaction_id=interaction_id, user_id=owner)
    assert row is not None
    assert row["task_type"] == "general"
    assert row["route_id"] == "provider:model"
    assert row["output_budget_tokens"] == 320
    assert store.get_interaction(interaction_id=interaction_id, user_id=other) is None
    assert store.interaction_count(user_id=owner) == 1
    assert store.interaction_count(user_id=other) == 0


def test_feedback_interaction_survives_restart_and_updates_in_place(pg_feedback_store):
    _, store, factory, owner, _, interaction_id = pg_feedback_store
    store.record_interaction(
        interaction_id=interaction_id, user_id=owner, task_type="general",
        route_id="provider:model", output_budget_tokens=320,
        completion_tokens=123, route_fingerprint="fingerprint-a",
    )
    restarted = PostgresFeedbackStore(factory)
    restarted.record_interaction(
        interaction_id=interaction_id, user_id=owner, task_type="reasoning",
        route_id="provider:model-v2", output_budget_tokens=640,
        completion_tokens=222, route_fingerprint="fingerprint-b",
    )
    row = restarted.get_interaction(interaction_id=interaction_id, user_id=owner)
    assert row is not None
    assert row["task_type"] == "reasoning"
    assert row["route_id"] == "provider:model-v2"
    assert row["output_budget_tokens"] == 640
    assert row["completion_tokens"] == 222
    assert row["route_fingerprint"] == "fingerprint-b"
    assert restarted.interaction_count(user_id=owner) == 1


def test_feedback_service_full_flow_survives_restart_and_is_tenant_scoped(pg_feedback_store):
    settings, _, _, owner, other, interaction_id = pg_feedback_store
    service = FeedbackService(settings)
    service.record_interaction(
        interaction_id=interaction_id, user_id=owner, task_type="general",
        route_id="provider:model", output_budget_tokens=320,
        completion_tokens=200, route_fingerprint="fp",
    )
    response = service.submit(
        user_id=owner,
        request=FeedbackSubmitRequest(
            interaction_id=interaction_id,
            rating=4,
            issues=[FeedbackIssue.TOO_LONG],
            comment="shorter next time",
        ),
    )
    assert response.duplicate is False
    assert response.reward_credits == 5
    assert response.preference_updated is True
    assert response.credit_balance == 5

    restarted = FeedbackService(settings)
    budget, learned = restarted.resolve_output_budget(
        user_id=owner, task_type="general", verbosity="auto", hard_cap=1000
    )
    assert learned is True
    assert budget == 256
    profile = restarted.profile(user_id=owner)
    assert profile.feedback_count == 1
    assert profile.credit_balance == 5
    assert profile.issue_counts["too_long"] == 1
    assert restarted.profile(user_id=other).feedback_count == 0
    assert restarted.credit_balance(user_id=other) == 0

    duplicate = restarted.submit(
        user_id=owner,
        request=FeedbackSubmitRequest(interaction_id=interaction_id, rating=5),
    )
    assert duplicate.duplicate is True
    assert duplicate.reward_credits == 0
    assert duplicate.credit_balance == 5


def test_feedback_service_survey_cadence_uses_postgres(pg_feedback_store):
    settings, _, _, owner, _, interaction_id = pg_feedback_store
    service = FeedbackService(settings)
    for index in range(5):
        service.record_interaction(
            interaction_id=f"{interaction_id}-{index}", user_id=owner,
            task_type="general", route_id="route", output_budget_tokens=320,
            completion_tokens=100, route_fingerprint="fp",
        )
    assert service.should_offer_survey(user_id=owner) is True

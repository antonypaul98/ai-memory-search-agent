"""Real-Postgres acceptance for tenant-scoped feedback interaction persistence."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_feedback_store import PostgresFeedbackStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS


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
        raise AssertionError("Postgres feedback store opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    factory = get_postgres_connection_factory(settings)
    store = PostgresFeedbackStore(factory)
    nonce = uuid4().hex
    owner = f"feedback-owner-{nonce}"
    other = f"feedback-other-{nonce}"
    interaction_id = f"ans_{nonce}"
    try:
        yield store, factory, owner, other, interaction_id
    finally:
        with factory() as conn:
            conn.execute(
                "DELETE FROM answer_interactions WHERE user_id IN (%s, %s)",
                (owner, other),
            )
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_feedback_interaction_round_trip_and_tenant_isolation(pg_feedback_store):
    store, _, owner, other, interaction_id = pg_feedback_store
    store.record_interaction(
        interaction_id=interaction_id,
        user_id=owner,
        task_type="general",
        route_id="provider:model",
        output_budget_tokens=320,
        completion_tokens=123,
        route_fingerprint="fingerprint-a",
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
    store, factory, owner, _, interaction_id = pg_feedback_store
    store.record_interaction(
        interaction_id=interaction_id,
        user_id=owner,
        task_type="general",
        route_id="provider:model",
        output_budget_tokens=320,
        completion_tokens=123,
        route_fingerprint="fingerprint-a",
    )

    restarted = PostgresFeedbackStore(factory)
    restarted.record_interaction(
        interaction_id=interaction_id,
        user_id=owner,
        task_type="reasoning",
        route_id="provider:model-v2",
        output_budget_tokens=640,
        completion_tokens=222,
        route_fingerprint="fingerprint-b",
    )
    row = restarted.get_interaction(interaction_id=interaction_id, user_id=owner)
    assert row is not None
    assert row["task_type"] == "reasoning"
    assert row["route_id"] == "provider:model-v2"
    assert row["output_budget_tokens"] == 640
    assert row["completion_tokens"] == 222
    assert row["route_fingerprint"] == "fingerprint-b"
    assert restarted.interaction_count(user_id=owner) == 1

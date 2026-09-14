"""Selected ingest-agent persistence: real Postgres, tenant-scoped, no SQLite fallback."""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError, get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.ingest_agent import IngestCandidate, IngestRuleCreate
from app.services.ingest_agent import IngestAgent


def test_selected_ingest_agent_missing_dsn_never_opens_sqlite(monkeypatch, tmp_path):
    env_name = "P03_INGEST_AGENT_MISSING_DSN"
    monkeypatch.delenv(env_name, raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres ingest agent opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    settings = Settings(
        _env_file=None,
        memory_store_backend="postgres",
        postgres_dsn_env=env_name,
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    with pytest.raises(PostgresConfigurationError):
        IngestAgent(settings)
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()


@pytest.fixture
def pg_ingest_agent(monkeypatch, tmp_path):
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
        raise AssertionError("selected Postgres ingest agent opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    nonce = uuid4().hex
    owner, other = f"ingest-agent-owner-{nonce}", f"ingest-agent-other-{nonce}"
    factory = get_postgres_connection_factory(settings)
    agent = IngestAgent(settings)
    try:
        yield settings, agent, factory, owner, other
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM memory_events WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM ingest_agent_claims WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM ingest_agent_rules WHERE user_id IN (%s, %s)", (owner, other))
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_postgres_ingest_agent_rule_round_trip_and_tenant_isolation(pg_ingest_agent):
    settings, agent, _, owner, other = pg_ingest_agent
    created = agent.create_rule(
        user_id=owner,
        request=IngestRuleCreate(
            name="YouTube saves",
            connector_id="youtube",
            match={"goal": "postgres"},
            force_refresh=True,
        ),
    )
    assert not created.approved
    approved = agent.approve_rule(user_id=owner, rule_id=created.rule_id)
    assert approved.approved and approved.enabled

    restarted = IngestAgent(settings)
    fetched = restarted.get_rule(user_id=owner, rule_id=created.rule_id)
    assert fetched.match == {"goal": "postgres"}
    assert fetched.force_refresh is True
    with pytest.raises(KeyError):
        restarted.get_rule(user_id=other, rule_id=created.rule_id)


def test_postgres_ingest_agent_claims_deduplicate_and_failed_ingest_is_retryable(pg_ingest_agent):
    _, agent, _, owner, _ = pg_ingest_agent
    rule = agent.create_rule(
        user_id=owner,
        request=IngestRuleCreate(name="YouTube", connector_id="youtube"),
    )
    agent.approve_rule(user_id=owner, rule_id=rule.rule_id)
    candidate = IngestCandidate(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    item = MagicMock()
    item.model_dump.return_value = {"video_id": "dQw4w9WgXcQ"}
    with patch("app.services.ingest_agent.IngestService") as ingest:
        ingest.return_value.ingest_single_url.return_value = item
        first = agent.run_rule(user_id=owner, rule_id=rule.rule_id, candidates=[candidate])
        second = agent.run_rule(user_id=owner, rule_id=rule.rule_id, candidates=[candidate])
    assert first.ingested == 1
    assert second.duplicates == 1

    retry_rule = agent.create_rule(
        user_id=owner,
        request=IngestRuleCreate(name="Retry", connector_id="youtube"),
    )
    agent.approve_rule(user_id=owner, rule_id=retry_rule.rule_id)
    with patch("app.services.ingest_agent.IngestService") as ingest:
        ingest.return_value.ingest_single_url.side_effect = RuntimeError("deterministic failure")
        failed = agent.run_rule(user_id=owner, rule_id=retry_rule.rule_id, candidates=[candidate])
        failed_again = agent.run_rule(user_id=owner, rule_id=retry_rule.rule_id, candidates=[candidate])
    assert failed.failed == 1
    assert failed_again.failed == 1
    assert failed.duplicates == 0
    assert failed_again.duplicates == 0

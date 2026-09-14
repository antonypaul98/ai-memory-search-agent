"""Selected agent-runtime persistence: real Postgres, tenant-scoped, no SQLite fallback."""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError, get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.agent_runtime import AgentPolicyTier, AgentRunRequest, AgentRunStatus
from app.services.agent_runtime import AgentRuntime


def test_selected_agent_runtime_missing_dsn_never_opens_sqlite(monkeypatch, tmp_path):
    env_name = "P03_AGENT_RUNTIME_MISSING_DSN"
    monkeypatch.delenv(env_name, raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres agent runtime opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    settings = Settings(
        _env_file=None,
        memory_store_backend="postgres",
        postgres_dsn_env=env_name,
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    with pytest.raises(PostgresConfigurationError):
        AgentRuntime(settings)
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()


@pytest.fixture
def pg_agent_runtime(monkeypatch, tmp_path):
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
        raise AssertionError("selected Postgres agent runtime opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    nonce = uuid4().hex
    owner, other = f"agent-owner-{nonce}", f"agent-other-{nonce}"
    factory = get_postgres_connection_factory(settings)
    runtime = AgentRuntime(settings)
    try:
        yield settings, runtime, factory, owner, other
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM event_bus_events WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM agent_tool_calls WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM agent_runs WHERE user_id IN (%s, %s)", (owner, other))
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_postgres_agent_runtime_round_trips_and_is_tenant_isolated(pg_agent_runtime):
    settings, runtime, _, owner, other = pg_agent_runtime
    response = MagicMock()
    response.model_dump.return_value = {"query": "postgres", "results": []}
    with patch("app.services.agent_runtime.SearchService") as search:
        search.return_value.search.return_value = response
        run = runtime.run(
            user_id=owner,
            request=AgentRunRequest(
                task="search durable state",
                tool="search_memory",
                arguments={"query": "postgres"},
                policy_tier=AgentPolicyTier.READ_ONLY,
            ),
        )
    assert run.status == AgentRunStatus.COMPLETED
    assert len(run.tool_calls) == 1

    restarted = AgentRuntime(settings)
    fetched = restarted.get_run(user_id=owner, run_id=run.run_id)
    assert fetched.status == AgentRunStatus.COMPLETED
    assert fetched.tool_calls[0].tool == "search_memory"
    with pytest.raises(KeyError):
        restarted.get_run(user_id=other, run_id=run.run_id)


def test_postgres_agent_runtime_preserves_approval_and_failure_state(pg_agent_runtime):
    _, runtime, _, owner, _ = pg_agent_runtime
    pending = runtime.run(
        user_id=owner,
        request=AgentRunRequest(
            task="save a memory",
            tool="ingest_url",
            arguments={"url": "https://youtu.be/example"},
            policy_tier=AgentPolicyTier.WRITE_MEMORY,
        ),
    )
    assert pending.status == AgentRunStatus.AWAITING_APPROVAL
    assert pending.tool_calls == []

    with patch("app.services.agent_runtime.IngestService") as ingest:
        ingest.return_value.ingest_single_url.side_effect = RuntimeError("deterministic failure")
        failed = runtime.approve(user_id=owner, run_id=pending.run_id)
    assert failed.status == AgentRunStatus.FAILED
    assert len(failed.tool_calls) == 1
    assert failed.tool_calls[0].status == "failed"
    assert "RuntimeError" in failed.message

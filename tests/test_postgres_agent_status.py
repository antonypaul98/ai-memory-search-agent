"""Agent status production profile: selected Postgres state and no SQLite fallback."""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError, get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.user import UserPublic
from app.services.agent_status_service import AgentStatusService


def test_selected_agent_status_missing_dsn_never_opens_sqlite(monkeypatch, tmp_path):
    env_name = "P03_AGENT_STATUS_MISSING_DSN"
    monkeypatch.delenv(env_name, raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres agent status opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env=env_name,
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    with pytest.raises(PostgresConfigurationError):
        AgentStatusService(settings)
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()


@pytest.fixture
def pg_agent_status(monkeypatch, tmp_path):
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
        raise AssertionError("selected Postgres agent status opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    nonce = uuid4().hex
    owner, other = f"status-owner-{nonce}", f"status-other-{nonce}"
    factory = get_postgres_connection_factory(settings)
    service = AgentStatusService(settings)
    try:
        yield service, factory, owner, other
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM intelligence_events WHERE user_id IN (%s, %s)", (owner, other))
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_postgres_agent_status_search_history_is_durable_and_tenant_scoped(pg_agent_status):
    service, _, owner, other = pg_agent_status
    service.record_search(user_id=owner, query="  tenant private search  ")

    with patch(
        "app.services.agent_status_service.MemoryRepository.check_connection",
        return_value={"connected": False, "document_count": 0},
    ):
        owner_status = service.get_status(UserPublic(user_id=owner, display_name="Owner"))
        other_status = service.get_status(UserPublic(user_id=other, display_name="Other"))

    assert [event.query for event in owner_status.recent_searches] == ["tenant private search"]
    assert other_status.recent_searches == []


def test_postgres_agent_status_survives_restart_without_sqlite(pg_agent_status):
    service, _, owner, _ = pg_agent_status
    service.record_search(user_id=owner, query="restart evidence")

    restarted = AgentStatusService(service._settings)
    with patch(
        "app.services.agent_status_service.MemoryRepository.check_connection",
        return_value={"connected": False, "document_count": 0},
    ):
        status = restarted.get_status(UserPublic(user_id=owner))

    assert status.recent_searches[0].query == "restart evidence"

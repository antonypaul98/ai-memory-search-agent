"""Real-Postgres acceptance for tenant-scoped model usage accounting."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_model_usage_ledger import PostgresModelUsageLedger
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS


@pytest.fixture
def pg_model_usage(monkeypatch, tmp_path):
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
        raise AssertionError("Postgres model usage ledger opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    factory = get_postgres_connection_factory(settings)
    ledger = PostgresModelUsageLedger(factory)
    nonce = uuid4().hex
    owner = f"usage-owner-{nonce}"
    other = f"usage-other-{nonce}"
    try:
        yield ledger, factory, owner, other
    finally:
        with factory() as conn:
            conn.execute(
                "DELETE FROM model_route_usage WHERE user_id IN (%s, %s)",
                (owner, other),
            )
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_model_usage_round_trip_and_tenant_isolation(pg_model_usage):
    ledger, _, owner, other = pg_model_usage
    ledger.record(
        user_id=owner,
        route_id="provider:model",
        provider_id="provider",
        model_id="model",
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
    )
    ledger.record(
        user_id=owner,
        route_id="provider:model",
        provider_id="provider",
        model_id="model",
        prompt_tokens=5,
        completion_tokens=3,
        total_tokens=8,
    )

    assert ledger.today(user_id=owner, route_id="provider:model") == (2, 26)
    assert ledger.today(user_id=other, route_id="provider:model") == (0, 0)


def test_model_usage_survives_restart(pg_model_usage):
    ledger, factory, owner, _ = pg_model_usage
    ledger.record(
        user_id=owner,
        route_id="provider:model",
        provider_id="provider",
        model_id="model",
        prompt_tokens=4,
        completion_tokens=6,
        total_tokens=10,
    )

    restarted = PostgresModelUsageLedger(factory)
    assert restarted.today(user_id=owner, route_id="provider:model") == (1, 10)

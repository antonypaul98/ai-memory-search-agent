import os

import pytest

from app.config import Settings
from app.db.postgres_runtime import (
    PostgresConfigurationError,
    ensure_postgres_job_schema,
    get_postgres_connection_factory,
)


class Cursor:
    rowcount = 1

    def fetchone(self):
        return None


class Connection:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self.calls.append((" ".join(query.split()), params))
        return Cursor()


def test_job_store_backend_defaults_to_sqlite_and_accepts_postgres():
    assert Settings(_env_file=None).job_store_backend == "sqlite"
    assert Settings(_env_file=None, job_store_backend="postgres").job_store_backend == "postgres"


def test_postgres_connection_factory_fails_closed_when_dsn_is_missing(monkeypatch):
    monkeypatch.delenv("MEMORY_AGENT_TEST_DATABASE_URL", raising=False)
    settings = Settings(_env_file=None, postgres_dsn_env="MEMORY_AGENT_TEST_DATABASE_URL")

    with pytest.raises(PostgresConfigurationError, match="MEMORY_AGENT_TEST_DATABASE_URL"):
        get_postgres_connection_factory(settings)


def test_postgres_connection_factory_keeps_dsn_out_of_configuration_errors(monkeypatch):
    secret_dsn = "postgresql://private-user:private-password@example.invalid/memory"
    monkeypatch.setenv("MEMORY_AGENT_TEST_DATABASE_URL", secret_dsn)
    settings = Settings(
        _env_file=None,
        postgres_dsn_env="MEMORY_AGENT_TEST_DATABASE_URL",
        postgres_connect_timeout_sec=0,
    )

    with pytest.raises(PostgresConfigurationError) as exc_info:
        get_postgres_connection_factory(settings)

    assert secret_dsn not in str(exc_info.value)
    assert "private-password" not in str(exc_info.value)


def test_postgres_schema_uses_native_types_and_required_indexes():
    calls = []

    def factory():
        return Connection(calls)

    ensure_postgres_job_schema(factory, lease_seconds=90)

    sql = "\n".join(query for query, _ in calls)
    assert "CREATE TABLE IF NOT EXISTS background_jobs" in sql
    assert "created_at TIMESTAMPTZ NOT NULL" in sql
    assert "paused BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "force_refresh BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "CREATE TABLE IF NOT EXISTS job_items" in sql
    assert "UNIQUE(job_id, item_key)" in sql
    assert "REFERENCES background_jobs(job_id) ON DELETE CASCADE" in sql
    assert "idx_background_jobs_runnable" in sql
    assert "idx_job_items_claim" in sql
    assert "idx_job_items_tenant" in sql
    assert "CREATE TABLE IF NOT EXISTS job_item_leases" in sql
    assert "lease_until TIMESTAMPTZ NOT NULL" in sql


def test_postgres_schema_rejects_invalid_lease_duration():
    with pytest.raises(ValueError, match="lease_seconds must be positive"):
        ensure_postgres_job_schema(lambda: Connection([]), lease_seconds=0)

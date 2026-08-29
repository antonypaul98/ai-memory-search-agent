from contextlib import contextmanager

import pytest

from app.config import Settings
from app.db import job_store_factory
from app.models.reflection import ReflectionInput


def test_sqlite_backend_remains_default(monkeypatch):
    settings = Settings(_env_file=None)
    sentinel = object()
    seen = []

    monkeypatch.setattr(job_store_factory, "JobStore", lambda value: (seen.append(value), sentinel)[1])

    assert job_store_factory.get_job_store(settings) is sentinel
    assert seen == [settings]


def test_postgres_backend_initializes_schema_and_facade(monkeypatch):
    settings = Settings(
        _env_file=None,
        job_store_backend="postgres",
        job_lease_seconds=77,
    )
    connection_factory = object()
    calls = []
    facade = object()

    monkeypatch.setattr(
        job_store_factory,
        "get_postgres_connection_factory",
        lambda value: (calls.append(("factory", value)), connection_factory)[1],
    )
    monkeypatch.setattr(
        job_store_factory,
        "ensure_postgres_job_schema",
        lambda factory, lease_seconds: calls.append(("schema", factory, lease_seconds)),
    )
    monkeypatch.setattr(
        job_store_factory,
        "PostgresJobStore",
        lambda factory, lease_seconds: (
            calls.append(("store", factory, lease_seconds)),
            facade,
        )[1],
    )

    assert job_store_factory.get_job_store(settings) is facade
    assert calls == [
        ("factory", settings),
        ("schema", connection_factory, 77),
        ("store", connection_factory, 77),
    ]


def test_postgres_execution_context_uses_selected_backend(monkeypatch):
    settings = Settings(_env_file=None, job_store_backend="postgres")
    reflection = ReflectionInput(reflection_note="Need this later")
    executed = []

    class Connection:
        def execute(self, sql, params):
            executed.append((sql, params))
            return self

        def fetchone(self):
            return {
                "user_id": "tenant-a",
                "reflection_json": reflection.model_dump_json(),
                "force_refresh": True,
            }

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(
        job_store_factory,
        "get_postgres_connection_factory",
        lambda value: connect,
    )

    context = job_store_factory.get_job_execution_context(settings, "job-123")

    assert context.user_id == "tenant-a"
    assert context.reflection == reflection
    assert context.force_refresh is True
    assert executed and "WHERE job_id = %s" in executed[0][0]
    assert "?" not in executed[0][0]
    assert executed[0][1] == ("job-123",)


def test_execution_context_missing_job_fails_closed(monkeypatch):
    settings = Settings(_env_file=None, job_store_backend="postgres")

    class Connection:
        def execute(self, sql, params):
            return self

        def fetchone(self):
            return None

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(
        job_store_factory,
        "get_postgres_connection_factory",
        lambda value: connect,
    )

    with pytest.raises(KeyError, match="Job not found"):
        job_store_factory.get_job_execution_context(settings, "missing")


def test_malformed_optional_reflection_remains_fail_soft(monkeypatch):
    settings = Settings(_env_file=None, job_store_backend="postgres")

    class Connection:
        def execute(self, sql, params):
            return self

        def fetchone(self):
            return {
                "user_id": "tenant-a",
                "reflection_json": "{not-json",
                "force_refresh": False,
            }

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(
        job_store_factory,
        "get_postgres_connection_factory",
        lambda value: connect,
    )

    context = job_store_factory.get_job_execution_context(settings, "job-123")

    assert context.user_id == "tenant-a"
    assert context.reflection is None
    assert context.force_refresh is False

from __future__ import annotations

import pytest

from app.config import Settings
from app.db import capture_store_factory
from app.db.capture_store import CaptureStore
from app.db.postgres_capture_store import PostgresCaptureStore
from app.db.postgres_runtime import PostgresConfigurationError


def test_capture_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "captures.db"))

    store = capture_store_factory.get_capture_store(settings)

    assert isinstance(store, CaptureStore)
    assert settings.capture_store_backend == "sqlite"


def test_postgres_capture_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_CAPTURE_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(capture_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        capture_store_factory.get_capture_store(settings)


def test_postgres_selection_uses_environment_owned_connection_factory(monkeypatch):
    connection_factory = object()
    calls: list[object] = []

    class FakePostgresCaptureStore:
        def __init__(self, resolved_factory):
            calls.append(resolved_factory)

    monkeypatch.setattr(
        capture_store_factory,
        "get_postgres_connection_factory",
        lambda settings: connection_factory,
    )
    monkeypatch.setattr(
        capture_store_factory,
        "PostgresCaptureStore",
        FakePostgresCaptureStore,
    )

    store = capture_store_factory.get_capture_store(Settings(capture_store_backend="postgres"))

    assert isinstance(store, FakePostgresCaptureStore)
    assert calls == [connection_factory]


def test_postgres_capture_schema_and_queries_keep_tenant_scope():
    statements: list[str] = []

    class FakeCursor:
        rowcount = 0

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append(" ".join(str(statement).split()))
            return FakeCursor()

    store = PostgresCaptureStore(lambda: FakeConnection())
    store.get_status("capture-1", user_id="tenant-a")
    store.get_retry_payload("capture-1", user_id="tenant-a")
    store.update_stage(
        "capture-1",
        user_id="tenant-a",
        status="completed",
        stage="completed",
        detail="done",
        error=None,
        title=None,
        now="2026-08-31T00:00:00+00:00",
    )
    store.rewrite_payload(
        "capture-1",
        user_id="tenant-a",
        payload_json="{}",
        now="2026-08-31T00:00:00+00:00",
    )

    joined = "\n".join(statements)
    assert "idx_captures_tenant_updated ON captures(user_id" in joined
    assert "idx_captures_tenant_hash ON captures(user_id, url_hash)" in joined
    tenant_queries = [s for s in statements if "capture_id = %s" in s]
    assert tenant_queries
    assert all("user_id = %s" in s for s in tenant_queries)


def test_postgres_capture_delete_is_exact_tenant_and_returns_count():
    calls: list[tuple[str, tuple | None]] = []

    class FakeCursor:
        rowcount = 3

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            normalized = " ".join(str(statement).split())
            calls.append((normalized, params))
            return FakeCursor()

    store = PostgresCaptureStore(lambda: FakeConnection())
    calls.clear()

    assert store.delete_for_user(user_id="tenant-a") == 3
    assert calls == [("DELETE FROM captures WHERE user_id = %s", ("tenant-a",))]


def test_postgres_capture_delete_rejects_blank_owner_before_connection():
    connections = 0

    def connection_factory():
        nonlocal connections
        connections += 1
        raise AssertionError("blank owner must fail before opening Postgres")

    store = object.__new__(PostgresCaptureStore)
    store._connection_factory = connection_factory

    with pytest.raises(ValueError, match="user_id is required"):
        store.delete_for_user(user_id="   ")

    assert connections == 0
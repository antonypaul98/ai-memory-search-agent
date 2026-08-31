from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.db.auth_store import AuthStore
from app.db.auth_store_factory import get_auth_store
from app.db.postgres_auth_store import PostgresAuthStore, ensure_postgres_auth_schema
from app.db.postgres_runtime import PostgresConfigurationError


class FakeCursor:
    def __init__(self, row=None, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])
        self.calls: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, params=None):
        self.calls.append((" ".join(sql.split()), params))
        row = self.rows.pop(0) if self.rows else None
        if isinstance(row, FakeCursor):
            return row
        return FakeCursor(row=row)


class FakeFactory:
    def __init__(self, connections: list[FakeConnection] | None = None) -> None:
        self.connections = list(connections or [])
        self.created: list[FakeConnection] = []

    @contextmanager
    def __call__(self):
        conn = self.connections.pop(0) if self.connections else FakeConnection()
        self.created.append(conn)
        yield conn


def test_auth_store_factory_keeps_sqlite_as_safe_default(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "auth.db"))

    store = get_auth_store(settings)

    assert isinstance(store, AuthStore)


def test_auth_store_factory_postgres_is_explicit_and_initializes_schema(monkeypatch):
    settings = Settings(auth_store_backend="postgres")
    factory = FakeFactory()
    seen = {}

    monkeypatch.setattr(
        "app.db.auth_store_factory.get_postgres_connection_factory",
        lambda supplied: factory,
    )
    monkeypatch.setattr(
        "app.db.auth_store_factory.ensure_postgres_auth_schema",
        lambda supplied: seen.setdefault("factory", supplied),
    )

    store = get_auth_store(settings)

    assert isinstance(store, PostgresAuthStore)
    assert seen["factory"] is factory


def test_auth_store_factory_postgres_never_falls_back_without_dsn(monkeypatch):
    env_name = "TEST_MEMORY_AGENT_DATABASE_URL"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(auth_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError, match=env_name):
        get_auth_store(settings)


def test_postgres_auth_schema_creates_users_sessions_and_indexes():
    factory = FakeFactory()

    ensure_postgres_auth_schema(factory)

    statements = "\n".join(sql for sql, _ in factory.created[0].calls)
    assert "CREATE TABLE IF NOT EXISTS users" in statements
    assert "CREATE TABLE IF NOT EXISTS sessions" in statements
    assert "REFERENCES users(user_id) ON DELETE CASCADE" in statements
    assert "idx_sessions_user_id" in statements
    assert "idx_sessions_expires_at" in statements


def test_postgres_local_user_is_idempotent():
    factory = FakeFactory()
    store = PostgresAuthStore(Settings(), factory)

    store.ensure_local_user()

    sql, params = factory.created[0].calls[0]
    assert "ON CONFLICT (user_id) DO NOTHING" in sql
    assert params[0] == "local-default"


def test_postgres_resolve_token_deletes_only_expired_matching_token_then_reads_active():
    row = {
        "user_id": "tenant-a",
        "email": "person@example.com",
        "display_name": "Person",
    }
    conn = FakeConnection(rows=[None, row])
    factory = FakeFactory([conn])
    store = PostgresAuthStore(Settings(), factory)

    user = store.resolve_token("session-secret")

    assert user is not None
    assert user.user_id == "tenant-a"
    assert user.email == "person@example.com"
    delete_sql, delete_params = conn.calls[0]
    select_sql, select_params = conn.calls[1]
    assert "DELETE FROM sessions WHERE token = %s AND expires_at <= %s" in delete_sql
    assert delete_params[0] == "session-secret"
    assert isinstance(delete_params[1], datetime)
    assert delete_params[1].tzinfo == timezone.utc
    assert "WHERE s.token = %s AND s.expires_at > %s" in select_sql
    assert select_params[0] == "session-secret"


def test_postgres_blank_session_token_does_not_touch_database():
    factory = FakeFactory()
    store = PostgresAuthStore(Settings(), factory)

    assert store.resolve_token("   ") is None
    assert factory.created == []

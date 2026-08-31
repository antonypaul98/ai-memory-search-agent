from __future__ import annotations

import pytest

from app.config import Settings
from app.db import import_run_store_factory
from app.db.import_run_store import ImportRunStore
from app.db.postgres_import_run_store import PostgresImportRunStore
from app.db.postgres_runtime import PostgresConfigurationError


def test_import_run_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "imports.db"))

    store = import_run_store_factory.get_import_run_store(settings)

    assert isinstance(store, ImportRunStore)
    assert settings.bookmark_store_backend == "sqlite"


def test_postgres_import_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_IMPORT_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(bookmark_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        import_run_store_factory.get_import_run_store(settings)


def test_postgres_selection_uses_environment_owned_connection_factory(monkeypatch):
    connection_factory = object()
    calls: list[object] = []

    class FakePostgresImportRunStore:
        def __init__(self, resolved_factory):
            calls.append(resolved_factory)

    monkeypatch.setattr(
        import_run_store_factory,
        "get_postgres_connection_factory",
        lambda settings: connection_factory,
    )
    monkeypatch.setattr(
        import_run_store_factory,
        "PostgresImportRunStore",
        FakePostgresImportRunStore,
    )

    store = import_run_store_factory.get_import_run_store(
        Settings(bookmark_store_backend="postgres")
    )

    assert isinstance(store, FakePostgresImportRunStore)
    assert calls == [connection_factory]


def test_postgres_import_schema_and_updates_are_tenant_scoped():
    statements: list[tuple[str, tuple | list | None]] = []

    class FakeCursor:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return FakeCursor()

    store = PostgresImportRunStore(lambda: FakeConnection())
    schema_sql = "\n".join(statement for statement, _ in statements)
    assert "idx_import_items_tenant ON import_run_items(user_id, import_id, id)" in schema_sql

    statements.clear()
    store.update_run(
        import_id="run-1",
        user_id="tenant-a",
        fields={"status": "running"},
        now="2026-08-31T00:00:00+00:00",
    )
    store.update_item(
        item_id=7,
        user_id="tenant-a",
        status="completed",
        detail="done",
        error=None,
        external_id="ext-1",
        now="2026-08-31T00:00:01+00:00",
    )

    assert any(
        "WHERE import_id = %s AND user_id = %s" in statement
        for statement, _ in statements
    )
    assert any(
        "WHERE id = %s AND user_id = %s" in statement
        for statement, _ in statements
    )


def test_sqlite_import_store_blocks_cross_tenant_reads_and_updates(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "imports.db"))
    store = ImportRunStore(settings)
    store.create(
        import_id="run-1",
        user_id="tenant-a",
        connector_id="bookmarks.v1",
        items=[("https://example.com", "Example")],
        now="2026-08-31T00:00:00+00:00",
    )

    with pytest.raises(KeyError):
        store.get(import_id="run-1", user_id="tenant-b", item_limit=10)

    item = store.list_pending_items(import_id="run-1", user_id="tenant-a")[0]
    store.update_item(
        item_id=item["id"],
        user_id="tenant-b",
        status="completed",
        detail="wrong tenant",
        error=None,
        external_id="",
        now="2026-08-31T00:00:01+00:00",
    )
    result = store.get(import_id="run-1", user_id="tenant-a", item_limit=10)
    assert result["items"][0]["status"] == "queued"

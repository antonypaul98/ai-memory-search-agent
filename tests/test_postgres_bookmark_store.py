from __future__ import annotations

import pytest

from app.config import Settings
from app.db import bookmark_store_factory
from app.db.bookmark_store import BookmarkStore
from app.db.postgres_bookmark_store import PostgresBookmarkStore
from app.db.postgres_runtime import PostgresConfigurationError


def test_bookmark_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "bookmarks.db"))

    store = bookmark_store_factory.get_bookmark_store(settings)

    assert isinstance(store, BookmarkStore)
    assert settings.bookmark_store_backend == "sqlite"


def test_postgres_bookmark_store_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_BOOKMARK_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(bookmark_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        bookmark_store_factory.get_bookmark_store(settings)


def test_postgres_selection_uses_environment_owned_connection_factory(monkeypatch):
    connection_factory = object()
    calls: list[object] = []

    class FakePostgresBookmarkStore:
        def __init__(self, resolved_factory):
            calls.append(resolved_factory)

    monkeypatch.setattr(
        bookmark_store_factory,
        "get_postgres_connection_factory",
        lambda settings: connection_factory,
    )
    monkeypatch.setattr(
        bookmark_store_factory,
        "PostgresBookmarkStore",
        FakePostgresBookmarkStore,
    )

    store = bookmark_store_factory.get_bookmark_store(Settings(bookmark_store_backend="postgres"))

    assert isinstance(store, FakePostgresBookmarkStore)
    assert calls == [connection_factory]


def test_postgres_bookmark_schema_and_snapshot_updates_keep_tenant_scope():
    statements: list[tuple[str, tuple | None]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((" ".join(str(statement).split()), params))
            return self

    store = PostgresBookmarkStore(lambda: FakeConnection())
    store.sync_snapshot(
        user_id="tenant-a",
        source_browser="chrome",
        items=[
            {
                "browser_bookmark_id": "bookmark-1",
                "folder_path": "Work",
                "url": "https://example.com/a",
                "url_hash": "hash-a",
                "title": "Example",
            }
        ],
        snapshot_complete=True,
        now="2026-08-31T00:00:00+00:00",
    )

    sql = "\n".join(statement for statement, _ in statements)
    assert "UNIQUE(user_id, browser_bookmark_id)" in sql
    assert "idx_browser_bookmarks_tenant_hash ON browser_bookmarks(user_id, url_hash)" in sql
    removal = next((entry for entry in statements if "removed_in_browser = TRUE" in entry[0]), None)
    assert removal is not None
    assert "WHERE user_id = %s AND source_browser = %s" in removal[0]
    assert removal[1][:3] == ("2026-08-31T00:00:00+00:00", "tenant-a", "chrome")


def test_partial_snapshot_never_marks_unseen_bookmarks_removed():
    statements: list[str] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append(" ".join(str(statement).split()))
            return self

    store = PostgresBookmarkStore(lambda: FakeConnection())
    statements.clear()
    store.sync_snapshot(
        user_id="tenant-a",
        source_browser="chrome",
        items=[],
        snapshot_complete=False,
        now="2026-08-31T00:00:00+00:00",
    )

    assert not any("removed_in_browser = TRUE" in statement for statement in statements)

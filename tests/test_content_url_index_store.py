from __future__ import annotations

import pytest

from app.config import Settings
from app.db import content_url_index_store_factory
from app.db.content_url_index_store import ContentUrlIndexStore
from app.db.postgres_content_url_index_store import PostgresContentUrlIndexStore
from app.db.postgres_runtime import PostgresConfigurationError
from app.services import cross_duplicate_service
from app.services.cross_duplicate_service import CrossConnectorDuplicateDetector
from app.services.deduplication_service import hash_text


def test_content_url_index_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "dedup.db"))

    store = content_url_index_store_factory.get_content_url_index_store(settings)

    assert isinstance(store, ContentUrlIndexStore)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_content_url_index_selection_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_CONTENT_URL_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        content_url_index_store_factory.get_content_url_index_store(settings)


def test_postgres_content_hash_lookup_is_tenant_scoped_and_deterministic():
    statements: list[tuple[str, tuple | None]] = []

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

    store = PostgresContentUrlIndexStore(lambda: FakeConnection())
    statements.clear()
    assert store.find_by_content_hash(user_id="tenant-a", content_hash="content-1") is None

    statement, params = statements[-1]
    assert "WHERE user_id = %s AND content_hash = %s" in statement
    assert "ORDER BY created_at ASC, url_hash ASC LIMIT 1" in statement
    assert params == ("tenant-a", "content-1")


def test_postgres_register_uses_composite_tenant_url_identity():
    statements: list[tuple[str, tuple | None]] = []

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

    store = PostgresContentUrlIndexStore(lambda: FakeConnection())
    schema_sql = "\n".join(statement for statement, _ in statements)
    assert "PRIMARY KEY (user_id, url_hash)" in schema_sql
    statements.clear()

    store.register(
        user_id="tenant-a",
        url_hash="url-1",
        canonical_url="https://example.com/a",
        content_hash="content-1",
        source_type="web",
        connector_id="web.v1",
        external_id="external-1",
        memory_id="memory-1",
        created_at="2026-09-10T00:00:00+00:00",
    )

    statement, params = statements[-1]
    assert "ON CONFLICT(user_id, url_hash) DO UPDATE" in statement
    assert params is not None
    assert params[0:4] == (
        "tenant-a",
        "url-1",
        "https://example.com/a",
        "content-1",
    )


def test_detector_routes_exact_tenant_through_selected_store(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeStore:
        def find_by_url_hash(self, **kwargs):
            calls.append(("url", kwargs))
            return None

        def find_by_content_hash(self, **kwargs):
            calls.append(("content", kwargs))
            return None

        def register(self, **kwargs):
            calls.append(("register", kwargs))

        def known_url_hashes(self, **kwargs):
            calls.append(("known", kwargs))
            return {"known-hash"}

    fake_store = FakeStore()
    monkeypatch.setattr(
        cross_duplicate_service,
        "get_content_url_index_store",
        lambda settings: fake_store,
    )
    detector = CrossConnectorDuplicateDetector(Settings())

    report = detector.check(
        user_id="tenant-a",
        canonical_url=" https://example.com/a ",
        content_hash="content-1",
    )
    detector.register(
        user_id="tenant-a",
        canonical_url="https://example.com/a",
        content_hash="content-1",
        source_type="web",
        connector_id="web.v1",
        external_id="external-1",
        memory_id="memory-1",
    )

    assert report.is_duplicate is False
    assert calls[0] == (
        "url",
        {"user_id": "tenant-a", "url_hash": hash_text("https://example.com/a")},
    )
    assert calls[1] == (
        "content",
        {"user_id": "tenant-a", "content_hash": "content-1"},
    )
    assert calls[2][0] == "register"
    assert calls[2][1]["user_id"] == "tenant-a"
    assert calls[2][1]["url_hash"] == hash_text("https://example.com/a")

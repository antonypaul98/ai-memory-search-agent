import os
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.concept_capsule_store_factory import get_concept_capsule_store
from app.db.content_url_index_store_factory import get_content_url_index_store
from app.db.import_run_store_factory import get_import_run_store
from app.db.knowledge_graph_store_factory import get_selected_knowledge_graph_store
from app.db.postgres_concept_capsule_store import PostgresConceptCapsuleStore
from app.db.postgres_content_url_index_store import PostgresContentUrlIndexStore
from app.db.postgres_import_run_store import PostgresImportRunStore
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from scripts.validate_production_storage_profile import (
    RELATIONAL_STORE_BACKEND_FIELDS,
    production_storage_profile_errors,
    validate_production_storage_profile,
)


def _production_settings(**overrides):
    values = {field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_storage_profile_accepts_all_postgres_backends():
    settings = _production_settings(postgres_dsn_env="DATABASE_URL")

    assert production_storage_profile_errors(settings) == []
    validate_production_storage_profile(settings)


def test_production_profile_routes_inherited_relational_stores_to_postgres(monkeypatch):
    test_dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN", "").strip()
    if not test_dsn:
        pytest.skip("MEMORY_AGENT_TEST_POSTGRES_DSN is required for Postgres selector integration proof")
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    settings = _production_settings(postgres_dsn_env="DATABASE_URL")

    assert isinstance(get_import_run_store(settings), PostgresImportRunStore)
    assert isinstance(get_selected_knowledge_graph_store(settings), PostgresKnowledgeGraphStore)


def test_production_profile_inherited_store_bootstrap_never_opens_sqlite(monkeypatch):
    test_dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN", "").strip()
    if not test_dsn:
        pytest.skip("MEMORY_AGENT_TEST_POSTGRES_DSN is required for zero-SQLite integration proof")
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    settings = _production_settings(postgres_dsn_env="DATABASE_URL")

    def reject_sqlite(*args, **kwargs):
        raise AssertionError("production Postgres selector fanout must not open relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)

    assert isinstance(get_import_run_store(settings), PostgresImportRunStore)
    assert isinstance(get_selected_knowledge_graph_store(settings), PostgresKnowledgeGraphStore)
    assert isinstance(get_concept_capsule_store(settings), PostgresConceptCapsuleStore)
    assert isinstance(get_content_url_index_store(settings), PostgresContentUrlIndexStore)


def test_production_profile_import_run_round_trip_is_postgres_only_and_tenant_scoped(monkeypatch):
    test_dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN", "").strip()
    if not test_dsn:
        pytest.skip("MEMORY_AGENT_TEST_POSTGRES_DSN is required for Postgres runtime acceptance proof")
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    settings = _production_settings(postgres_dsn_env="DATABASE_URL")

    def reject_sqlite(*args, **kwargs):
        raise AssertionError("production Postgres import runtime must not open relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)

    store = get_import_run_store(settings)
    assert isinstance(store, PostgresImportRunStore)

    nonce = uuid4().hex
    import_id = f"p03-runtime-{nonce}"
    owner_id = f"owner-{nonce}"
    other_id = f"other-{nonce}"
    now = datetime.now(timezone.utc).isoformat()
    items = [(f"https://example.com/{nonce}/a", "alpha"), (f"https://example.com/{nonce}/b", "beta")]

    store.create(
        import_id=import_id,
        user_id=owner_id,
        connector_id="p03-runtime-acceptance",
        items=items,
        now=now,
    )

    owner_run = store.get(import_id=import_id, user_id=owner_id, item_limit=10)
    assert owner_run["import_id"] == import_id
    assert owner_run["user_id"] == owner_id
    assert owner_run["items_total"] == 2
    assert [item["url"] for item in owner_run["items"]] == [url for url, _ in items]

    assert any(run["import_id"] == import_id for run in store.list(user_id=owner_id, limit=100))
    assert all(run["import_id"] != import_id for run in store.list(user_id=other_id, limit=100))
    with pytest.raises(KeyError, match="Import not found"):
        store.get(import_id=import_id, user_id=other_id, item_limit=10)


def test_production_storage_profile_reports_every_sqlite_backend_deterministically():
    settings = _production_settings(
        auth_store_backend="sqlite",
        semantic_cache_store_backend="sqlite",
    )

    assert production_storage_profile_errors(settings) == [
        "auth_store_backend must be 'postgres' for the production profile; got 'sqlite'",
        "semantic_cache_store_backend must be 'postgres' for the production profile; got 'sqlite'",
    ]


def test_production_storage_profile_rejects_missing_dsn_environment_name():
    settings = _production_settings(postgres_dsn_env="   ")

    assert production_storage_profile_errors(settings) == [
        "postgres_dsn_env must name the environment variable containing the Postgres DSN"
    ]

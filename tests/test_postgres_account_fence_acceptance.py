"""Real-Postgres races: drain active writes, reject late writes, retain neighbors."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.account_erasure_fence import AccountErasureFence, require_active_tenant
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS


@pytest.fixture
def fenced_pg(monkeypatch, tmp_path):
    dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real Postgres DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    schema = "fence_acceptance_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    alias = "P03_FENCE_" + uuid4().hex
    monkeypatch.setenv(alias, make_conninfo(dsn, options=f"-c search_path={schema}"))
    settings = Settings(_env_file=None, **{f: "postgres" for f in RELATIONAL_STORE_BACKEND_FIELDS},
                        postgres_dsn_env=alias, chroma_persist_dir=str(tmp_path / "chroma"), jobs_enabled=False)
    factory = get_postgres_connection_factory(settings)
    try:
        yield settings, factory
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_fence_drains_started_transaction_without_blocking_neighbor(fenced_pg):
    _, factory = fenced_pg
    fence = AccountErasureFence(factory)
    active, release, fencing, finished = Event(), Event(), Event(), Event()
    def writer():
        with factory() as conn:
            require_active_tenant(conn, user_id="target")
            active.set()
            assert release.wait(10)
    def eraser():
        fencing.set()
        fence.fence(user_id="target")
        finished.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(writer)
        assert active.wait(10)
        erasing = pool.submit(eraser)
        assert fencing.wait(10)
        try:
            assert not finished.wait(0.2), "fence raced past an active transaction"
            with factory() as conn:
                conn.execute("SET LOCAL lock_timeout='2s'")
                require_active_tenant(conn, user_id="neighbor")
        finally:
            release.set()
        writing.result(timeout=10)
        erasing.result(timeout=10)
    fence.fence(user_id="target")
    with factory() as conn:
        with pytest.raises(PermissionError):
            require_active_tenant(conn, user_id="target")
    assert fence.is_fenced(user_id="target")
    assert not fence.is_fenced(user_id="neighbor")


def test_late_relational_and_vector_writers_cannot_recreate_erased_state(fenced_pg):
    settings, factory = fenced_pg
    from app.db.memory_store_factory import get_memory_store
    from app.db.postgres_capture_store import PostgresCaptureStore
    from app.db.postgres_import_run_store import PostgresImportRunStore
    from app.db.postgres_oauth_token_store import PostgresOAuthTokenStore
    from app.db.postgres_event_store import PostgresEventStore
    from app.db.hierarchical_store import HierarchicalStore
    from app.models.capsule import MemoryCapsule
    from app.models.video import SourceType
    memories = get_memory_store(settings)
    captures = PostgresCaptureStore(factory)
    imports = PostgresImportRunStore(factory)
    oauth = PostgresOAuthTokenStore(factory)
    events = PostgresEventStore(factory)
    hierarchy = HierarchicalStore(settings)
    fence = AccountErasureFence(factory)
    writes = [
        lambda owner: memories.upsert(user_id=owner, source_type=SourceType.WEB, external_id="shared",
                                       canonical_url="https://example.test/shared", title="private memory"),
        lambda owner: captures.create(capture_id=owner, user_id=owner, url="https://example.test", url_hash="hash",
                                      title="capture", source_type="web", payload_json="{}", now="2026-09-21T00:00:00Z"),
        lambda owner: imports.create(import_id=owner, user_id=owner, connector_id="test", items=[], now="2026-09-21T00:00:00Z"),
        lambda owner: oauth.put(user_id=owner, connector_id="test", encrypted_payload=b"test-only",
                                scopes_json="[]", expires_at=None, now="2026-09-21T00:00:00Z"),
        lambda owner: events.insert_event(event_id=owner, user_id=owner, event_type="test", aggregate_type="",
                                          aggregate_id="", actor="test", request_id=None, payload_json="{}", created_at="2026-09-21T00:00:00Z"),
        lambda owner: hierarchy.upsert_capsule(MemoryCapsule(video_id="shared", title="test"), [1., 0., 0.], user_id=owner),
    ]
    fence.fence(user_id="target")
    for write in writes:
        with pytest.raises(PermissionError, match="account erasure"):
            write("target")
        write("neighbor")
    with factory() as conn:
        for table in ("memory_records", "captures", "import_runs", "connector_oauth_tokens", "memory_events"):
            assert conn.execute(f"SELECT count(*) AS n FROM {table} WHERE user_id='target'").fetchone()["n"] == 0
            assert conn.execute(f"SELECT count(*) AS n FROM {table} WHERE user_id='neighbor'").fetchone()["n"] == 1
    assert hierarchy._collection(settings.capsule_collection_name).get(where={"user_id": "target"})["ids"] == []
    assert len(hierarchy._collection(settings.capsule_collection_name).get(where={"user_id": "neighbor"})["ids"]) == 1

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


def test_confirmed_account_erasure_blocks_enabled_producers_and_preserves_neighbor(fenced_pg, monkeypatch):
    from app.services.privacy_service import PrivacyService
    from app.services.privacy_erasure import erase_confirmed_account
    from app.db.postgres_runtime import ensure_postgres_job_schema
    from app.db.postgres_job_store import PostgresJobStore
    from app.db.postgres_import_run_store import PostgresImportRunStore
    from app.db.postgres_oauth_token_store import PostgresOAuthTokenStore
    from app.db.postgres_agent_runtime_store import PostgresAgentRuntimeStore
    from app.models.video import SourceType
    from app.models.capsule import MemoryCapsule
    from app.services.playlist_service import PlaylistVideoEntry
    settings, factory = fenced_pg
    monkeypatch.setenv(settings.auth_secret_env, "test-only-account-fence-secret")
    privacy = PrivacyService(settings)
    ensure_postgres_job_schema(factory)
    jobs = PostgresJobStore(factory)
    imports = PostgresImportRunStore(factory)
    oauth = PostgresOAuthTokenStore(factory)
    agents = PostgresAgentRuntimeStore(factory)
    now = "2026-09-21T00:00:00Z"
    owners = [privacy._auth_store.create_user(email=f"{label}@example.test", password="test-password",
                                            display_name=label).user_id for label in ("target", "neighbor")]
    target, neighbor = owners
    def writes(owner, nonce):
        return {
            "canonical_ingress": lambda: privacy._memory_store.upsert(user_id=owner, source_type=SourceType.WEB,
                external_id="source-" + nonce, canonical_url="https://example.test/" + nonce, title="private"),
            "capture": lambda: privacy._capture_store.create(capture_id=owner + nonce, user_id=owner,
                url="https://example.test", url_hash=nonce, title="private", source_type="web", payload_json="{}", now=now),
            "import_replay": lambda: imports.create(import_id=owner + nonce, user_id=owner, connector_id="test",
                items=[("https://example.test", "private")], now=now),
            "oauth_callback": lambda: oauth.put(user_id=owner, connector_id="test", encrypted_payload=b"test",
                scopes_json="[]", expires_at=None, now=now),
            "agent": lambda: agents.create_run(user_id=owner, run_id=owner + nonce, agent_id="test", task="private",
                tool="search", arguments_json="{}", policy_tier="read_only", status="queued", message="", created_at=now),
            "background_job": lambda: jobs.create_playlist_job(user_id=owner, playlist_id="test", playlist_title="test",
                entries=[PlaylistVideoEntry("shared", "https://example.test", "private")], reflection=None, force_refresh=False),
            "session": lambda: privacy._auth_store.create_session(owner),
            "late_vector": lambda: privacy._hstore.upsert_capsule(MemoryCapsule(video_id="orphan-" + nonce), [1., 0., 0.], user_id=owner),
        }
    for owner in owners:
        for write in writes(owner, "seed").values():
            write()
    target_claim = jobs.claim_next_item(worker_id="stale", user_id=target)
    neighbor_claim = jobs.claim_next_item(worker_id="neighbor", user_id=neighbor)
    assert target_claim and neighbor_claim
    preserved = privacy.export_user_data(user_id=neighbor)
    with pytest.raises(ValueError, match="confirmation"):
        erase_confirmed_account(settings, user_id=target, confirm_user_id=neighbor, privacy_service=privacy)
    assert not AccountErasureFence(factory).is_fenced(user_id=target)
    assert privacy._memory_store.list_recent(user_id=target)
    result = erase_confirmed_account(settings, user_id=target, confirm_user_id=target, privacy_service=privacy)
    assert result["deleted"] and result["account_fenced"]
    assert result["memory_deleted_count"] == 1
    assert privacy.export_user_data(user_id=neighbor) == preserved
    assert privacy._auth_store.get_user_for_export(user_id=target) is None
    assert privacy._hstore._collection(settings.capsule_collection_name).get(where={"user_id": target})["ids"] == []
    for attempt in ("late", "late"):  # Same replay twice must stay rejected.
        for label, write in writes(target, attempt).items():
            with pytest.raises(PermissionError, match="account erasure"):
                write()
    with pytest.raises(PermissionError):
        imports.update_run(import_id=target + "seed", user_id=target, now=now, fields={"status": "running"})
    with pytest.raises(PermissionError):
        privacy._capture_store.rewrite_payload(target + "seed", user_id=target, payload_json="{}", now=now)
    with pytest.raises(PermissionError):
        agents.create_tool_call(user_id=target, run_id=target + "seed", tool="search", arguments_json="{}", created_at=now)
    job_id, item_key, _ = target_claim
    assert not jobs.heartbeat_item(job_id=job_id, item_key=item_key, worker_id="stale")
    assert not jobs.complete_item(job_id=job_id, item_key=item_key, worker_id="stale", status="completed")
    with pytest.raises(PermissionError):
        jobs.retry_failed(job_id, user_id=target)
    with factory() as conn:
        tables = conn.execute("SELECT table_name FROM information_schema.columns WHERE table_schema=current_schema() AND column_name='user_id'").fetchall()
        for row in tables:
            table = row["table_name"]
            if table != "account_erasure_fences":
                assert conn.execute(f'SELECT count(*) AS n FROM "{table}" WHERE user_id=%s', (target,)).fetchone()["n"] == 0, table
    assert erase_confirmed_account(settings, user_id=target, confirm_user_id=target, privacy_service=privacy)["deleted"]
    for write in writes(neighbor, "new").values():
        write()
    job_id, item_key, _ = neighbor_claim
    assert jobs.heartbeat_item(job_id=job_id, item_key=item_key, worker_id="neighbor")
    assert jobs.complete_item(job_id=job_id, item_key=item_key, worker_id="neighbor", status="completed")


def test_migration_replay_rejects_erased_owner_atomically(fenced_pg, tmp_path):
    from tests.test_postgres_import_run_migration import _source_db
    from app.db.postgres_import_run_migration import migrate_import_runs_to_postgres, preview_import_run_migration
    settings, factory = fenced_pg
    settings = settings.model_copy(update={"sqlite_path": _source_db(tmp_path)})
    AccountErasureFence(factory).fence(user_id="alice")
    assert preview_import_run_migration(settings).runs == 2
    for _ in range(2):
        with pytest.raises(PermissionError, match="account erasure"):
            migrate_import_runs_to_postgres(settings, connection_factory=factory)
        with factory() as conn:
            assert conn.execute("SELECT count(*) AS n FROM import_runs").fetchone()["n"] == 0
    first = migrate_import_runs_to_postgres(settings, user_id="bob", connection_factory=factory)
    again = migrate_import_runs_to_postgres(settings, user_id="bob", connection_factory=factory)
    assert first.runs_inserted == 1 and again.runs_inserted == 0
    assert again.runs_skipped_existing == 1

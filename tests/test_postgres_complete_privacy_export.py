"""Production export must not inherit UI limits or trust child ownership."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_privacy_export import export_postgres_history
from app.db.postgres_runtime import get_postgres_connection_factory, ensure_postgres_job_schema
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.video import SourceType
from app.services.privacy_service import PrivacyService, dump_export_markdown, load_export_markdown


@pytest.fixture
def export_context(monkeypatch, tmp_path):
    dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real Postgres DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "full_export_" + uuid4().hex
    alias = "P03_EXPORT_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    monkeypatch.setenv(alias, make_conninfo(dsn, options=f"-c search_path={schema}"))
    settings = Settings(_env_file=None, **{f: "postgres" for f in RELATIONAL_STORE_BACKEND_FIELDS},
                        postgres_dsn_env=alias, sqlite_path=str(tmp_path / "forbidden.db"),
                        chroma_persist_dir=str(tmp_path / "chroma"), jobs_enabled=False)
    def reject(*args, **kwargs):
        raise AssertionError("production export opened relational SQLite")
    monkeypatch.setattr(sqlite3, "connect", reject)
    try:
        factory = get_postgres_connection_factory(settings)
        ensure_postgres_job_schema(factory)
        yield settings, factory
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_complete_export_crosses_old_caps_and_preserves_canonical_history(export_context):
    settings, factory = export_context
    service = PrivacyService(settings)
    memories = {}
    for owner in ("target", "neighbor"):
        memories[owner] = service._memory_store.upsert(
            user_id=owner, source_type=SourceType.WEB, external_id=owner,
            canonical_url="https://example.test/" + owner, title=owner,
        )
    # Seed history through the canonical store API rather than assuming an upsert
    # creates a version row. This proves the exporter returns real persisted history.
    service._memory_store.add_version(memory=memories["target"], reason="export acceptance")
    service._memory_store.add_version(memory=memories["neighbor"], reason="neighbor isolation")
    with factory() as conn:
        conn.execute("""INSERT INTO memory_records
            (memory_id,user_id,source_type,external_id,canonical_url,title,lifecycle_state,verification_status,created_at,updated_at)
            SELECT 'bulk-'||n,'target','web','bulk-'||n,'https://example.test/'||n,'record '||n,
                   lifecycle_state,verification_status,created_at,updated_at
            FROM memory_records CROSS JOIN generate_series(1,10000) n WHERE user_id='target'""")
        conn.execute("""INSERT INTO captures(capture_id,user_id,url,url_hash,status,created_at,updated_at)
            SELECT 'capture-'||n,'target','https://example.test/'||n,'hash-'||n,'queued',now(),now()
            FROM generate_series(1,2001) n""")
        conn.execute("""INSERT INTO browser_bookmarks(user_id,browser_bookmark_id,url,url_hash,last_synced_at)
            SELECT 'target','bookmark-'||n,'https://example.test/'||n,'hash-'||n,now()
            FROM generate_series(1,5001) n""")
        conn.execute("""INSERT INTO background_jobs(job_id,user_id,job_type,status,created_at)
            SELECT 'job-'||n,'target','test','queued',now() FROM generate_series(1,501) n""")
    payload = service.export_user_data(user_id="target")
    assert len(payload["memories"]) == 10001
    assert len(payload["captures"]) == 2001
    assert len(payload["browser_bookmarks"]) == 5001
    assert len(payload["jobs"]) == 501
    assert all(row["user_id"] == "target" for row in payload["memories"])
    assert payload["history"]["memory_versions"]
    assert all(row["user_id"] == "target" for row in payload["history"]["memory_versions"])
    restored = load_export_markdown(dump_export_markdown(payload))
    assert len(restored["memories"]) == 10001
    assert restored["history"] == payload["history"]


def test_history_export_redacts_credentials_and_rejects_corrupt_parent_ownership(export_context):
    _, factory = export_context
    from app.db.postgres_agent_runtime_store import PostgresAgentRuntimeStore
    from app.db.postgres_oauth_token_store import PostgresOAuthTokenStore
    agents = PostgresAgentRuntimeStore(factory)
    tokens = PostgresOAuthTokenStore(factory)
    for owner in ("target", "neighbor"):
        agents.create_run(run_id=owner, user_id=owner, agent_id="fixture", task="task", tool="search",
                          arguments_json='{"access_token":"never-export","query":"portable"}',
                          policy_tier="read", status="running", message="", created_at="2026-09-21")
        agents.create_tool_call(run_id=owner, user_id=owner, tool="search", arguments_json="{}", created_at="2026-09-21")
        tokens.put(user_id=owner, connector_id="fixture", encrypted_payload=b"never-export",
                   scopes_json='["read"]', expires_at=None, now="2026-09-21")
    exported = export_postgres_history(factory, user_id="target")
    assert "never-export" not in str(exported)
    assert "portable" in str(exported)
    assert len(exported["agent_tool_calls"]) == 1
    assert exported["connector_oauth_tokens"][0]["scopes_json"] == '["read"]'
    with factory() as conn:
        conn.execute("UPDATE agent_tool_calls SET user_id='target' WHERE run_id='neighbor'")
    # A false child label cannot move a neighbor's tool call into target export.
    assert len(export_postgres_history(factory, user_id="target")["agent_tool_calls"]) == 1
    with pytest.raises(ValueError, match="inconsistent canonical ownership"):
        export_postgres_history(factory, user_id="neighbor")

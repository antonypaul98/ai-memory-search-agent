"""Erasure follows canonical parents even when legacy child labels disagree."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.db.postgres_agent_runtime_store import PostgresAgentRuntimeStore
from app.db.postgres_import_run_store import PostgresImportRunStore


@pytest.fixture
def pg_parent_privacy():
    dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real Postgres DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from psycopg.rows import dict_row

    schema = "parent_privacy_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
    try:
        yield lambda: psycopg.connect(scoped, row_factory=dict_row)
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("domain", ["imports", "agents"])
def test_parent_owned_erasure_preserves_mislabeled_neighbor_and_retries(pg_parent_privacy, domain):
    factory = pg_parent_privacy
    if domain == "imports":
        store = PostgresImportRunStore(factory)
        parent, child, key = "import_runs", "import_run_items", "import_id"
        for owner in ("target", "neighbor"):
            store.create(import_id=owner, user_id=owner, connector_id="fixture",
                         items=[("https://example.test/" + owner, owner)], now="2026-09-21T00:00:00Z")
    else:
        store = PostgresAgentRuntimeStore(factory)
        parent, child, key = "agent_runs", "agent_tool_calls", "run_id"
        for owner in ("target", "neighbor"):
            store.create_run(run_id=owner, user_id=owner, agent_id="fixture", task="private task",
                             tool="search", arguments_json="{}", policy_tier="read", status="running",
                             message="", created_at="2026-09-21T00:00:00Z")
            store.create_tool_call(user_id=owner, run_id=owner, tool="search",
                                   arguments_json="{}", created_at="2026-09-21T00:00:00Z")
    # Deliberately model legacy corruption in both directions. Parent identity
    # remains canonical, regardless of which account the child label claims.
    with factory() as conn:
        conn.execute(f"UPDATE {child} SET user_id = CASE WHEN {key}='target' THEN 'neighbor' ELSE 'target' END")
        before = conn.execute(f"SELECT * FROM {child} WHERE {key}='neighbor'").fetchall()
        conn.execute("""CREATE FUNCTION fail_parent_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected erasure failure'; END $$""")
        conn.execute(f"CREATE TRIGGER fail_parent_delete BEFORE DELETE ON {parent} FOR EACH ROW EXECUTE FUNCTION fail_parent_delete()")
    with pytest.raises(Exception, match="injected erasure failure"):
        store.delete_for_user(user_id="target")
    with factory() as conn:
        assert conn.execute(f"SELECT count(*) AS n FROM {child}").fetchone()["n"] == 2
        assert conn.execute(f"SELECT count(*) AS n FROM {parent}").fetchone()["n"] == 2
        conn.execute(f"DROP TRIGGER fail_parent_delete ON {parent}")
    store.delete_for_user(user_id="target")
    store.delete_for_user(user_id="target")
    with factory() as conn:
        assert conn.execute(f"SELECT * FROM {child} WHERE {key}='neighbor'").fetchall() == before
        assert conn.execute(f"SELECT * FROM {child} WHERE {key}='target'").fetchall() == []
        assert conn.execute(f"SELECT user_id FROM {parent}").fetchall() == [{"user_id": "neighbor"}]

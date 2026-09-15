"""Real-Postgres acceptance for exact-tenant intelligence erasure."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.intelligence_privacy import delete_user_intelligence, export_user_intelligence
from app.db.postgres_concept_capsule_store import PostgresConceptCapsuleStore
from app.db.postgres_creator_profile_store import PostgresCreatorProfileStore
from app.db.postgres_intelligence_event_store import PostgresIntelligenceEventStore
from app.db.postgres_learning_edge_store import PostgresLearningEdgeStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS


def test_intelligence_erasure_is_atomic_and_two_tenant_isolated(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "p03_intel_privacy_" + uuid4().hex
    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "P03_INTEL_PRIVACY_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env=dsn_alias,
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    factory = get_postgres_connection_factory(settings)
    PostgresConceptCapsuleStore(factory)
    PostgresCreatorProfileStore(factory)
    PostgresLearningEdgeStore(factory)
    PostgresIntelligenceEventStore(factory)

    owner = "intel-owner-" + uuid4().hex
    other = "intel-other-" + uuid4().hex
    now = datetime.now(timezone.utc)

    try:
        with factory() as conn:
            for user_id, suffix in ((owner, "owner"), (other, "other")):
                conn.execute(
                    "INSERT INTO concept_capsules (capsule_id,user_id,name,normalized_name,summary,topic_ids_json,memory_video_ids_json,creator_names_json,progress_total,progress_completed,updated_at) VALUES (%s,%s,%s,%s,%s,'[]','[]','[]',1,1,%s)",
                    (f"cap-{suffix}", user_id, f"{suffix} concept", f"{suffix}-concept", f"private {suffix} capsule", now),
                )
                conn.execute(
                    "INSERT INTO creator_profiles (creator_id,user_id,name,normalized_name,updated_at) VALUES (%s,%s,%s,%s,%s)",
                    (f"creator-{suffix}", user_id, f"{suffix} creator", f"{suffix}-creator", now),
                )
                conn.execute(
                    "INSERT INTO learning_edges (edge_id,user_id,source_video_id,target_video_id,relation,strength,evidence,evidence_refs_json,created_at) VALUES (%s,%s,%s,%s,'related',0.8,%s,'[]',%s)",
                    (f"edge-{suffix}", user_id, f"source-{suffix}", f"target-{suffix}", f"private {suffix} edge", now),
                )
                conn.execute(
                    "INSERT INTO intelligence_events (user_id,event_type,topic,video_id,query,created_at) VALUES (%s,'query',%s,%s,%s,%s)",
                    (user_id, f"topic-{suffix}", f"video-{suffix}", f"private {suffix} query", now),
                )

        owner_before = export_user_intelligence(factory, user_id=owner)
        other_before = export_user_intelligence(factory, user_id=other)
        assert all(len(rows) == 1 for rows in owner_before.values())
        assert all(len(rows) == 1 for rows in other_before.values())

        trigger = "reject_intel_capsule_delete_" + uuid4().hex
        with factory() as conn:
            conn.execute(sql.SQL("""CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF OLD.user_id = {} THEN RAISE EXCEPTION 'injected intelligence deletion failure';
                END IF; RETURN OLD; END $$""").format(sql.Identifier(trigger), sql.Literal(owner)))
            conn.execute(sql.SQL(
                "CREATE TRIGGER {} BEFORE DELETE ON concept_capsules FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(sql.Identifier(trigger), sql.Identifier(trigger)))

        try:
            with pytest.raises(psycopg.Error, match="injected intelligence deletion failure"):
                delete_user_intelligence(factory, user_id=owner)
            assert export_user_intelligence(factory, user_id=owner) == owner_before
            assert export_user_intelligence(factory, user_id=other) == other_before
        finally:
            with factory() as conn:
                conn.execute(sql.SQL("DROP TRIGGER {} ON concept_capsules").format(sql.Identifier(trigger)))
                conn.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(trigger)))

        assert delete_user_intelligence(factory, user_id=owner) == {
            "learning_edges": 1,
            "intelligence_events": 1,
            "concept_capsules": 1,
            "creator_profiles": 1,
        }
        assert delete_user_intelligence(factory, user_id=owner) == {
            "learning_edges": 0,
            "intelligence_events": 0,
            "concept_capsules": 0,
            "creator_profiles": 0,
        }
        assert all(not rows for rows in export_user_intelligence(factory, user_id=owner).values())
        assert export_user_intelligence(factory, user_id=other) == other_before
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

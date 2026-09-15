"""Real-Postgres acceptance for exact-tenant knowledge-graph erasure."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.knowledge_graph_privacy import delete_user_graph, export_user_graph
from app.db.knowledge_graph_store_factory import get_selected_knowledge_graph_store
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.knowledge_graph import EntityType, RelationPredicate


def test_graph_erasure_is_atomic_and_two_tenant_isolated(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "p03_graph_privacy_" + uuid4().hex
    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "P03_GRAPH_PRIVACY_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env=dsn_alias,
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )

    owner = "graph-owner-" + uuid4().hex
    other = "graph-other-" + uuid4().hex
    store = get_selected_knowledge_graph_store(settings)

    try:
        seeded = {}
        for user_id, suffix in ((owner, "owner"), (other, "other")):
            subject = store.upsert_entity(
                user_id=user_id, entity_type=EntityType.CONCEPT, name=f"{suffix} subject"
            )
            obj = store.upsert_entity(
                user_id=user_id, entity_type=EntityType.PROJECT, name=f"{suffix} project"
            )
            relation = store.upsert_relation(
                user_id=user_id,
                subject_entity_id=subject.entity_id,
                predicate=RelationPredicate.RELATED_TO,
                object_entity_id=obj.entity_id,
                memory_id=f"memory-{suffix}",
            )
            store.link_memory_entity(
                user_id=user_id,
                memory_id=f"memory-{suffix}",
                entity_id=subject.entity_id,
                mention_context=f"private {suffix} evidence",
            )
            seeded[user_id] = (subject, obj, relation)

        owner_before = export_user_graph(settings, user_id=owner)
        other_before = export_user_graph(settings, user_id=other)
        assert len(owner_before["entities"]) == len(other_before["entities"]) == 2
        assert len(owner_before["relations"]) == len(other_before["relations"]) == 1
        assert len(owner_before["memory_entity_links"]) == len(other_before["memory_entity_links"]) == 1

        trigger = "reject_graph_entity_delete_" + uuid4().hex
        with store._connection_factory() as conn:
            conn.execute(sql.SQL("""CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF OLD.user_id = {} THEN RAISE EXCEPTION 'injected graph deletion failure';
                END IF; RETURN OLD; END $$""").format(sql.Identifier(trigger), sql.Literal(owner)))
            conn.execute(sql.SQL(
                "CREATE TRIGGER {} BEFORE DELETE ON kg_entities FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(sql.Identifier(trigger), sql.Identifier(trigger)))

        try:
            with pytest.raises(psycopg.Error, match="injected graph deletion failure"):
                delete_user_graph(settings, user_id=owner, store=store)
            # Links and relations are deleted before entities; the injected final-step
            # failure must roll the whole graph-domain transaction back.
            assert export_user_graph(settings, user_id=owner) == owner_before
            assert export_user_graph(settings, user_id=other) == other_before
        finally:
            with store._connection_factory() as conn:
                conn.execute(sql.SQL("DROP TRIGGER {} ON kg_entities").format(sql.Identifier(trigger)))
                conn.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(trigger)))

        assert delete_user_graph(settings, user_id=owner, store=store) == {
            "memory_entity_links": 1,
            "relations": 1,
            "entities": 2,
        }
        assert delete_user_graph(settings, user_id=owner, store=store) == {
            "memory_entity_links": 0,
            "relations": 0,
            "entities": 0,
        }
        assert export_user_graph(settings, user_id=owner) == {
            "entities": [], "relations": [], "memory_entity_links": []
        }
        assert export_user_graph(settings, user_id=other) == other_before
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

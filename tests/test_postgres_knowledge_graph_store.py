from __future__ import annotations

import pytest

from app.config import Settings
from app.db import knowledge_graph_store_factory
from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from app.db.postgres_runtime import PostgresConfigurationError
from app.models.knowledge_graph import EntityType, RelationPredicate


def test_knowledge_graph_store_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "graph.db"))
    assert isinstance(
        knowledge_graph_store_factory.get_selected_knowledge_graph_store(settings),
        KnowledgeGraphStore,
    )


def test_postgres_knowledge_graph_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_KG_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)
    with pytest.raises(PostgresConfigurationError):
        knowledge_graph_store_factory.get_selected_knowledge_graph_store(settings)


def test_knowledge_graph_schema_preserves_tenant_identity_and_deterministic_indexes():
    statements = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            statements.append((" ".join(str(sql).split()), params))
            return self

    PostgresKnowledgeGraphStore(lambda: Conn())
    sql = "\n".join(statement for statement, _ in statements)
    assert "UNIQUE(user_id, entity_type, normalized_name)" in sql
    assert "PRIMARY KEY(user_id, memory_id, entity_id)" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_relations_identity" in sql
    assert "COALESCE(memory_id, '')" in sql
    assert "idx_kg_relations_subject" in sql
    assert "idx_kg_relations_object" in sql


def test_entity_reads_and_search_are_exact_tenant_and_deterministic():
    statements = []

    class Result:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            statements.append((" ".join(str(sql).split()), params))
            return Result()

    store = PostgresKnowledgeGraphStore(lambda: Conn())
    statements.clear()
    assert store.get_entity("entity-1", user_id="tenant-a") is None
    assert "entity_id = %s AND user_id = %s" in statements[-1][0]
    assert statements[-1][1] == ("entity-1", "tenant-a")

    assert (
        store.search_entities(
            user_id="tenant-a",
            query="Python",
            entity_type=EntityType.TECHNOLOGY,
            limit=7,
        )
        == []
    )
    query, params = statements[-1]
    assert "user_id = %s" in query
    assert "ORDER BY updated_at DESC, entity_id ASC" in query
    assert params == ("tenant-a", "technology", "%python%", "%Python%", 7)


def test_relation_write_checks_both_entities_belong_to_tenant():
    statements = []

    class Result:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            statements.append((" ".join(str(sql).split()), params))
            return Result()

    store = PostgresKnowledgeGraphStore(lambda: Conn())
    statements.clear()
    with pytest.raises(ValueError, match="not owned by tenant"):
        store.upsert_relation(
            user_id="tenant-a",
            subject_entity_id="entity-a",
            predicate=RelationPredicate.RELATED_TO,
            object_entity_id="entity-b",
        )
    assert statements[0][1] == ("entity-a", "tenant-a")


def test_memory_links_require_exact_tenant_entity_ownership():
    from app.models.knowledge_graph import MemoryEntityLink

    statements = []

    class Result:
        def fetchone(self):
            return None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            statements.append((" ".join(str(sql).split()), params))
            return Result()

    store = PostgresKnowledgeGraphStore(lambda: Conn())
    statements.clear()
    with pytest.raises(ValueError, match="not owned by tenant"):
        store.link_memory_entity(
            MemoryEntityLink(memory_id="memory-1", entity_id="entity-1"),
            user_id="tenant-a",
        )
    assert statements[0][1] == ("entity-1", "tenant-a")

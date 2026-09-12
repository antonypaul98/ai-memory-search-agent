from __future__ import annotations

from app.config import Settings
from app.db.knowledge_graph_privacy import delete_memory_graph_links
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore


class _Cursor:
    rowcount = 1

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        packed = tuple(params) if params is not None else None
        self.calls.append((normalized, packed))
        return _Cursor()


class _Factory:
    def __init__(self):
        self.connection = _Connection()

    def __call__(self):
        return self.connection


def test_postgres_graph_privacy_delete_is_exact_tenant_scoped():
    factory = _Factory()
    store = PostgresKnowledgeGraphStore(factory)
    factory.connection.calls.clear()  # ignore schema setup

    deleted = delete_memory_graph_links(
        settings=Settings(memory_store_backend="postgres"),
        memory_id="memory-1",
        user_id="tenant-a",
        store=store,
    )

    assert deleted == 1
    assert factory.connection.calls == [
        (
            "DELETE FROM kg_memory_entities WHERE memory_id = %s AND user_id = %s",
            ("memory-1", "tenant-a"),
        )
    ]


def test_graph_privacy_boundary_fails_closed_for_unknown_store():
    class _UnknownStore:
        pass

    try:
        delete_memory_graph_links(
            settings=Settings(),
            memory_id="memory-1",
            user_id="tenant-a",
            store=_UnknownStore(),
        )
    except RuntimeError as exc:
        assert "unsupported selected knowledge-graph privacy backend" in str(exc)
    else:
        raise AssertionError("unknown graph privacy backend did not fail closed")

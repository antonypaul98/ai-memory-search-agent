from __future__ import annotations

import pytest

from app.db.knowledge_graph_privacy import delete_user_graph
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore


class _Cursor:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Connection:
    def __init__(self, calls: list[tuple[str, tuple[str, ...]]]) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[str, ...]):
        self.calls.append((" ".join(sql.split()), params))
        return _Cursor(1)


def _postgres_store(factory) -> PostgresKnowledgeGraphStore:
    store = PostgresKnowledgeGraphStore.__new__(PostgresKnowledgeGraphStore)
    store._connection_factory = factory
    return store


def test_delete_user_graph_scopes_every_delete_to_exact_tenant() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    store = _postgres_store(lambda: _Connection(calls))

    result = delete_user_graph(None, user_id="tenant-a", store=store)  # type: ignore[arg-type]

    assert result == {"memory_entity_links": 1, "relations": 1, "entities": 1}
    assert calls == [
        ("DELETE FROM kg_memory_entities WHERE user_id = %s", ("tenant-a",)),
        ("DELETE FROM kg_relations WHERE user_id = %s", ("tenant-a",)),
        ("DELETE FROM kg_entities WHERE user_id = %s", ("tenant-a",)),
    ]


def test_delete_user_graph_rejects_blank_owner_before_connection() -> None:
    opened = False

    def factory():
        nonlocal opened
        opened = True
        return _Connection([])

    store = _postgres_store(factory)

    with pytest.raises(ValueError, match="user_id"):
        delete_user_graph(None, user_id="  ", store=store)  # type: ignore[arg-type]

    assert opened is False

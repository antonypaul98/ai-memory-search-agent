from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.db.knowledge_graph_privacy import export_user_graph
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from app.services import privacy_service


class _Cursor:
    rowcount = 0

    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


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
        now = datetime(2026, 9, 12, tzinfo=timezone.utc)
        if normalized.startswith("SELECT * FROM kg_entities"):
            return _Cursor(
                [
                    {
                        "entity_id": "entity-1",
                        "user_id": "tenant-a",
                        "entity_type": "person",
                        "name": "Ada",
                        "normalized_name": "ada",
                        "aliases_json": '["A"]',
                        "metadata_json": '{"source":"memory"}',
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            )
        if normalized.startswith("SELECT * FROM kg_relations"):
            return _Cursor(
                [
                    {
                        "relation_id": "relation-1",
                        "user_id": "tenant-a",
                        "subject_entity_id": "entity-1",
                        "predicate": "related_to",
                        "object_entity_id": "entity-2",
                        "memory_id": "memory-1",
                        "confidence": 0.8,
                        "metadata_json": '{"valid_from":"2026-09-01T00:00:00+00:00"}',
                        "created_at": now,
                    }
                ]
            )
        if normalized.startswith("SELECT * FROM kg_memory_entities"):
            return _Cursor(
                [
                    {
                        "memory_id": "memory-1",
                        "entity_id": "entity-1",
                        "user_id": "tenant-a",
                        "mention_context": "Ada",
                        "start_time": 1.0,
                        "end_time": 2.0,
                        "confidence": 0.9,
                    }
                ]
            )
        return _Cursor()


class _Factory:
    def __init__(self):
        self.connection = _Connection()

    def __call__(self):
        return self.connection


def test_postgres_graph_privacy_export_is_complete_and_exact_tenant_scoped():
    factory = _Factory()
    store = PostgresKnowledgeGraphStore(factory)
    factory.connection.calls.clear()  # ignore schema setup

    exported = export_user_graph(
        Settings(memory_store_backend="postgres"),
        user_id="tenant-a",
        store=store,
    )

    assert exported["entities"][0]["aliases"] == ["A"]
    assert exported["relations"][0]["valid_from"] == "2026-09-01T00:00:00+00:00"
    assert exported["memory_entity_links"][0]["memory_id"] == "memory-1"
    assert len(factory.connection.calls) == 3
    assert all("WHERE user_id = %s" in sql for sql, _ in factory.connection.calls)
    assert all(params == ("tenant-a",) for _, params in factory.connection.calls)


def test_graph_privacy_export_fails_closed_for_unknown_store():
    with pytest.raises(RuntimeError, match="unsupported selected knowledge-graph privacy backend"):
        export_user_graph(Settings(), user_id="tenant-a", store=object())


def test_privacy_service_export_routes_through_selected_graph_boundary():
    source = __import__("inspect").getsource(privacy_service.PrivacyService.export_user_data)
    assert "export_user_graph(self._settings, user_id=user_id)" in source
    assert '"knowledge_graph": knowledge_graph' in source

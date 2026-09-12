from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_knowledge_graph_migration import (
    migrate_knowledge_graph_to_postgres,
    preview_knowledge_graph_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0, row=None) -> None:
        self.rowcount = rowcount
        self._row = row

    def fetchone(self):
        return self._row


class _FakePostgres:
    def __init__(self) -> None:
        self.entities: dict[str, tuple] = {}
        self.relations: dict[str, tuple] = {}
        self.links: dict[tuple[str, str, str], tuple] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else ()
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select entity_id,user_id,entity_type,name,normalized_name"):
            row = self.entities.get(str(values[0]))
            return _Cursor(0, row)
        if normalized.startswith("select relation_id,user_id,subject_entity_id,predicate"):
            row = self.relations.get(str(values[0]))
            return _Cursor(0, row)
        if normalized.startswith("select memory_id,entity_id,user_id,mention_context"):
            row = self.links.get((str(values[0]), str(values[1]), str(values[2])))
            return _Cursor(0, row)
        if normalized.startswith("insert into kg_entities"):
            if str(values[0]) in self.entities:
                return _Cursor(0)
            self.entities[str(values[0])] = values
            return _Cursor(1)
        if normalized.startswith("insert into kg_relations"):
            if str(values[0]) in self.relations:
                return _Cursor(0)
            self.relations[str(values[0])] = values
            return _Cursor(1)
        if normalized.startswith("insert into kg_memory_entities"):
            key = (str(values[2]), str(values[0]), str(values[1]))
            if key in self.links:
                return _Cursor(0)
            self.links[key] = values
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE kg_entities (
            entity_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, entity_type TEXT NOT NULL,
            name TEXT NOT NULL, normalized_name TEXT NOT NULL, aliases_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE kg_relations (
            relation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, subject_entity_id TEXT NOT NULL,
            predicate TEXT NOT NULL, object_entity_id TEXT NOT NULL, memory_id TEXT,
            confidence REAL NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE kg_memory_entities (
            memory_id TEXT NOT NULL, entity_id TEXT NOT NULL, user_id TEXT NOT NULL,
            mention_context TEXT NOT NULL, start_time REAL, end_time REAL, confidence REAL NOT NULL,
            PRIMARY KEY(memory_id, entity_id)
        );
        """)
        conn.executemany(
            "INSERT INTO kg_entities VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("e1", "alice", "person", "Ada Lovelace", "ada lovelace", "[]", "{}", "2026-09-10T10:00:00+00:00", "2026-09-10T10:00:00+00:00"),
                ("e2", "alice", "company", "Analytical Society", "analytical society", "[]", "{}", "2026-09-10T10:01:00+00:00", "2026-09-10T10:01:00+00:00"),
                ("e3", "bob", "person", "Grace Hopper", "grace hopper", "[]", "{}", "2026-09-10T10:02:00+00:00", "2026-09-10T10:02:00+00:00"),
            ],
        )
        conn.execute(
            "INSERT INTO kg_relations VALUES (?,?,?,?,?,?,?,?,?)",
            ("r1", "alice", "e1", "related_to", "e2", "m1", 0.9, '{"valid_from":"2026-09-10T10:00:00+00:00"}', "2026-09-10T10:03:00+00:00"),
        )
        conn.execute(
            "INSERT INTO kg_memory_entities VALUES (?,?,?,?,?,?,?)",
            ("m1", "e1", "alice", "Ada mention", 1.0, 2.0, 0.95),
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    assert preview_knowledge_graph_migration(settings).to_dict() == {
        "entities": 3,
        "relations": 1,
        "memory_links": 1,
        "tenants": 2,
    }
    assert preview_knowledge_graph_migration(settings, user_id="alice").to_dict() == {
        "entities": 2,
        "relations": 1,
        "memory_links": 1,
        "tenants": 1,
    }


def test_migration_is_read_only_deterministic_and_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_knowledge_graph_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_knowledge_graph_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.entities_inserted == 3
    assert first.relations_inserted == 1
    assert first.memory_links_inserted == 1
    assert second.entities_inserted == 0
    assert second.relations_inserted == 0
    assert second.memory_links_inserted == 0
    assert list(target.entities) == ["e1", "e2", "e3"]
    assert list(target.relations) == ["r1"]
    assert list(target.links) == [("alice", "m1", "e1")]


def test_tenant_scoped_migration_never_copies_other_tenant(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    target = _FakePostgres()
    report = migrate_knowledge_graph_to_postgres(
        settings, user_id="alice", connection_factory=lambda: target
    )
    assert report.entities_seen == 2
    assert set(target.entities) == {"e1", "e2"}


def test_malformed_json_fails_before_target_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE kg_entities SET metadata_json='{' WHERE entity_id='e1'")
    target = _FakePostgres()
    with pytest.raises(ValueError, match="invalid JSON"):
        migrate_knowledge_graph_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.entities == {}


def test_cross_tenant_relation_fails_before_target_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE kg_relations SET object_entity_id='e3' WHERE relation_id='r1'")
    target = _FakePostgres()
    with pytest.raises(ValueError, match="outside its tenant"):
        migrate_knowledge_graph_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.entities == {}


def test_blank_tenant_filter_and_missing_source_fail_closed(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_knowledge_graph_migration(settings, user_id=" ")
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        preview_knowledge_graph_migration(Settings(sqlite_path=str(missing)))
    assert not missing.exists()

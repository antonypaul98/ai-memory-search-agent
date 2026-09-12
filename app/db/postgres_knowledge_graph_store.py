"""Tenant-scoped Postgres persistence for the knowledge graph."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.db.knowledge_graph_store import normalize_entity_name, _parse_utc, _relation_active_at, _validate_temporal_window
from app.models.knowledge_graph import EntityType, GraphEntity, GraphNeighbor, GraphQueryResponse, GraphRelation, MemoryEntityLink, RelationPredicate

ConnectionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _entity(row: Any) -> GraphEntity:
    return GraphEntity(entity_id=row["entity_id"], user_id=row["user_id"], entity_type=EntityType(row["entity_type"]), name=row["name"], normalized_name=row["normalized_name"], aliases=json.loads(row["aliases_json"] or "[]"), metadata=json.loads(row["metadata_json"] or "{}"), created_at=_iso(row["created_at"]), updated_at=_iso(row["updated_at"]))


def _relation(row: Any) -> GraphRelation:
    metadata = json.loads(row["metadata_json"] or "{}")
    return GraphRelation(relation_id=row["relation_id"], user_id=row["user_id"], subject_entity_id=row["subject_entity_id"], predicate=RelationPredicate(row["predicate"]), object_entity_id=row["object_entity_id"], memory_id=row["memory_id"], confidence=float(row["confidence"]), metadata=metadata, valid_from=metadata.get("valid_from") or _iso(row["created_at"]), valid_to=metadata.get("valid_to"), created_at=_iso(row["created_at"]))


class PostgresKnowledgeGraphStore:
    """Exact-tenant graph storage preserving temporal evidence semantics."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS kg_entities (entity_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, entity_type TEXT NOT NULL, name TEXT NOT NULL, normalized_name TEXT NOT NULL, aliases_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, UNIQUE(user_id, entity_type, normalized_name))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_user_order ON kg_entities(user_id, updated_at DESC, entity_id ASC)")
            conn.execute("""CREATE TABLE IF NOT EXISTS kg_relations (relation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, subject_entity_id TEXT NOT NULL, predicate TEXT NOT NULL, object_entity_id TEXT NOT NULL, memory_id TEXT NULL, confidence DOUBLE PRECISION NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL, UNIQUE(user_id, subject_entity_id, predicate, object_entity_id, memory_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_relations_subject ON kg_relations(user_id, subject_entity_id, created_at DESC, relation_id ASC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_relations_object ON kg_relations(user_id, object_entity_id, created_at DESC, relation_id ASC)")
            conn.execute("""CREATE TABLE IF NOT EXISTS kg_memory_entities (memory_id TEXT NOT NULL, entity_id TEXT NOT NULL, user_id TEXT NOT NULL, mention_context TEXT NOT NULL DEFAULT '', start_time DOUBLE PRECISION NULL, end_time DOUBLE PRECISION NULL, confidence DOUBLE PRECISION NOT NULL, PRIMARY KEY(user_id, memory_id, entity_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_memory_entities_memory ON kg_memory_entities(user_id, memory_id, entity_id)")

    def upsert_entity(self, *, user_id: str, entity_type: EntityType, name: str, aliases: list[str] | None = None, metadata: dict | None = None, entity_id: str | None = None) -> GraphEntity:
        normalized = normalize_entity_name(name)
        if not user_id.strip() or not normalized:
            raise ValueError("user_id and entity name are required")
        now = _now()
        aliases = sorted(set(aliases or []))
        with self._connection_factory() as conn:
            row = conn.execute("SELECT * FROM kg_entities WHERE user_id = %s AND entity_type = %s AND normalized_name = %s FOR UPDATE", (user_id, entity_type.value, normalized)).fetchone()
            if row:
                merged_aliases = sorted(set(json.loads(row["aliases_json"] or "[]") + aliases))
                row = conn.execute("UPDATE kg_entities SET name=%s, aliases_json=%s, metadata_json=%s, updated_at=%s WHERE entity_id=%s AND user_id=%s RETURNING *", (name.strip(), json.dumps(merged_aliases), json.dumps(metadata or {}), now, row["entity_id"], user_id)).fetchone()
            else:
                row = conn.execute("INSERT INTO kg_entities (entity_id,user_id,entity_type,name,normalized_name,aliases_json,metadata_json,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", (entity_id or str(uuid.uuid4()), user_id, entity_type.value, name.strip(), normalized, json.dumps(aliases), json.dumps(metadata or {}), now, now)).fetchone()
        return _entity(row)

    def get_entity(self, entity_id: str, *, user_id: str) -> GraphEntity | None:
        with self._connection_factory() as conn:
            row = conn.execute("SELECT * FROM kg_entities WHERE entity_id = %s AND user_id = %s", (entity_id, user_id)).fetchone()
        return _entity(row) if row else None

    def search_entities(self, *, user_id: str, query: str = "", entity_type: EntityType | None = None, limit: int = 20) -> list[GraphEntity]:
        clauses = ["user_id = %s"]
        params: list[Any] = [user_id]
        if entity_type:
            clauses.append("entity_type = %s"); params.append(entity_type.value)
        if query.strip():
            clauses.append("(normalized_name LIKE %s OR name LIKE %s)"); params.extend([f"%{normalize_entity_name(query)}%", f"%{query.strip()}%"])
        params.append(limit)
        with self._connection_factory() as conn:
            rows = conn.execute(f"SELECT * FROM kg_entities WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC, entity_id ASC LIMIT %s", tuple(params)).fetchall()
        return [_entity(r) for r in rows]

    def _require_owned_entity(self, conn: Any, entity_id: str, user_id: str) -> None:
        if conn.execute("SELECT 1 FROM kg_entities WHERE entity_id = %s AND user_id = %s", (entity_id, user_id)).fetchone() is None:
            raise ValueError("graph entity is not owned by tenant")

    def upsert_relation(self, *, user_id: str, subject_entity_id: str, predicate: RelationPredicate, object_entity_id: str, memory_id: str | None = None, confidence: float = 1.0, metadata: dict | None = None, valid_from: str | None = None, valid_to: str | None = None) -> GraphRelation:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        now = _now()
        with self._connection_factory() as conn:
            self._require_owned_entity(conn, subject_entity_id, user_id); self._require_owned_entity(conn, object_entity_id, user_id)
            existing = conn.execute("SELECT * FROM kg_relations WHERE user_id=%s AND subject_entity_id=%s AND predicate=%s AND object_entity_id=%s AND COALESCE(memory_id,'')=COALESCE(%s,'') FOR UPDATE", (user_id, subject_entity_id, predicate.value, object_entity_id, memory_id)).fetchone()
            existing_meta = json.loads(existing["metadata_json"] or "{}") if existing else {}
            merged = dict(existing_meta); merged.update(metadata or {})
            created = _iso(existing["created_at"]) if existing else now.isoformat()
            effective_from = valid_from or merged.get("valid_from") or created
            effective_to = valid_to if valid_to is not None else merged.get("valid_to")
            _validate_temporal_window(effective_from, effective_to)
            merged["valid_from"] = effective_from
            if effective_to: merged["valid_to"] = effective_to
            else: merged.pop("valid_to", None)
            if existing:
                row = conn.execute("UPDATE kg_relations SET confidence=%s, metadata_json=%s WHERE relation_id=%s AND user_id=%s RETURNING *", (confidence, json.dumps(merged), existing["relation_id"], user_id)).fetchone()
            else:
                row = conn.execute("INSERT INTO kg_relations (relation_id,user_id,subject_entity_id,predicate,object_entity_id,memory_id,confidence,metadata_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", (str(uuid.uuid4()), user_id, subject_entity_id, predicate.value, object_entity_id, memory_id, confidence, json.dumps(merged), now)).fetchone()
        return _relation(row)

    def get_relation(self, relation_id: str, *, user_id: str) -> GraphRelation | None:
        with self._connection_factory() as conn:
            row = conn.execute("SELECT * FROM kg_relations WHERE relation_id=%s AND user_id=%s", (relation_id, user_id)).fetchone()
        return _relation(row) if row else None

    def close_relation(self, relation_id: str, *, user_id: str, valid_to: str | None = None) -> GraphRelation | None:
        relation = self.get_relation(relation_id, user_id=user_id)
        if relation is None: return None
        return self.upsert_relation(user_id=user_id, subject_entity_id=relation.subject_entity_id, predicate=relation.predicate, object_entity_id=relation.object_entity_id, memory_id=relation.memory_id, confidence=relation.confidence, metadata=relation.metadata, valid_from=relation.valid_from, valid_to=valid_to or _now().isoformat())

    def list_relations_for_entity(self, entity_id: str, *, user_id: str, direction: str = "both", at_time: str | None = None) -> list[GraphRelation]:
        rows: list[Any] = []
        with self._connection_factory() as conn:
            if direction in ("outgoing", "both"): rows.extend(conn.execute("SELECT * FROM kg_relations WHERE user_id=%s AND subject_entity_id=%s ORDER BY created_at DESC, relation_id ASC", (user_id, entity_id)).fetchall())
            if direction in ("incoming", "both"): rows.extend(conn.execute("SELECT * FROM kg_relations WHERE user_id=%s AND object_entity_id=%s ORDER BY created_at DESC, relation_id ASC", (user_id, entity_id)).fetchall())
        relations = [_relation(r) for r in rows]
        return [r for r in relations if _relation_active_at(r, at_time)] if at_time is not None else relations

    def link_memory_entity(self, link: MemoryEntityLink, *, user_id: str) -> None:
        with self._connection_factory() as conn:
            self._require_owned_entity(conn, link.entity_id, user_id)
            conn.execute("INSERT INTO kg_memory_entities (memory_id,entity_id,user_id,mention_context,start_time,end_time,confidence) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,memory_id,entity_id) DO UPDATE SET mention_context=EXCLUDED.mention_context,start_time=EXCLUDED.start_time,end_time=EXCLUDED.end_time,confidence=EXCLUDED.confidence", (link.memory_id, link.entity_id, user_id, link.mention_context, link.start_time, link.end_time, link.confidence))

    def list_memory_entities(self, memory_id: str, *, user_id: str) -> list[GraphEntity]:
        with self._connection_factory() as conn:
            rows = conn.execute("SELECT e.* FROM kg_entities e JOIN kg_memory_entities me ON me.entity_id=e.entity_id AND me.user_id=e.user_id WHERE me.memory_id=%s AND me.user_id=%s ORDER BY e.entity_type,e.name,e.entity_id", (memory_id, user_id)).fetchall()
        return [_entity(r) for r in rows]

    def neighbors(self, entity_id: str, *, user_id: str, depth: int = 1, at_time: str | None = None) -> GraphQueryResponse:
        depth = min(2, max(1, depth)); center = self.get_entity(entity_id, user_id=user_id)
        if not center: return GraphQueryResponse()
        seen_entities = {entity_id: center}; seen_relations: dict[str, GraphRelation] = {}; neighbors: list[GraphNeighbor] = []; frontier = {entity_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for eid in sorted(frontier):
                for rel in self.list_relations_for_entity(eid, user_id=user_id, direction="both", at_time=at_time):
                    seen_relations[rel.relation_id] = rel
                    other_id = rel.object_entity_id if rel.subject_entity_id == eid else rel.subject_entity_id
                    other = self.get_entity(other_id, user_id=user_id)
                    if not other: continue
                    seen_entities[other_id] = other
                    neighbors.append(GraphNeighbor(entity=other, relation=rel, direction="outgoing" if rel.subject_entity_id == eid else "incoming")); next_frontier.add(other_id)
            frontier = next_frontier - set(seen_entities)
        return GraphQueryResponse(entities=list(seen_entities.values()), relations=list(seen_relations.values()), neighbors=neighbors)

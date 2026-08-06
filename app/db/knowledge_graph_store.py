"""Knowledge graph persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate
from app.models.knowledge_graph import (
    EntityType,
    GraphEntity,
    GraphNeighbor,
    GraphQueryResponse,
    GraphRelation,
    MemoryEntityLink,
    RelationPredicate,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_entity_name(name: str) -> str:
    return " ".join(name.lower().split())


class KnowledgeGraphStore:
    """Entity, relation, and memory-entity link storage."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    def upsert_entity(
        self,
        *,
        user_id: str,
        entity_type: EntityType,
        name: str,
        aliases: list[str] | None = None,
        metadata: dict | None = None,
        entity_id: str | None = None,
    ) -> GraphEntity:
        normalized = normalize_entity_name(name)
        aliases = aliases or []
        now = _utc_now()
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM kg_entities
                WHERE user_id = ? AND entity_type = ? AND normalized_name = ?
                """,
                (user_id, entity_type.value, normalized),
            ).fetchone()
            if row:
                entity_id = row["entity_id"]
                merged_aliases = sorted(set(json.loads(row["aliases_json"] or "[]") + aliases))
                conn.execute(
                    """
                    UPDATE kg_entities
                    SET name = ?, aliases_json = ?, metadata_json = ?, updated_at = ?
                    WHERE entity_id = ?
                    """,
                    (name, json.dumps(merged_aliases), json.dumps(metadata or {}), now, entity_id),
                )
            else:
                entity_id = entity_id or str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO kg_entities (
                        entity_id, user_id, entity_type, name, normalized_name,
                        aliases_json, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        user_id,
                        entity_type.value,
                        name,
                        normalized,
                        json.dumps(aliases),
                        json.dumps(metadata or {}),
                        now,
                        now,
                    ),
                )
        entity = self.get_entity(entity_id, user_id=user_id)
        assert entity is not None
        return entity

    def get_entity(self, entity_id: str, *, user_id: str) -> GraphEntity | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM kg_entities WHERE entity_id = ? AND user_id = ?",
                (entity_id, user_id),
            ).fetchone()
        return _row_to_entity(row) if row else None

    def search_entities(
        self,
        *,
        user_id: str,
        query: str = "",
        entity_type: EntityType | None = None,
        limit: int = 20,
    ) -> list[GraphEntity]:
        clauses = ["user_id = ?"]
        params: list = [user_id]
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type.value)
        if query.strip():
            like = f"%{normalize_entity_name(query)}%"
            clauses.append("(normalized_name LIKE ? OR name LIKE ?)")
            params.extend([like, f"%{query.strip()}%"])
        sql = f"""
            SELECT * FROM kg_entities
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            LIMIT ?
        """
        params.append(limit)
        with get_connection(self._settings) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_entity(row) for row in rows]

    def upsert_relation(
        self,
        *,
        user_id: str,
        subject_entity_id: str,
        predicate: RelationPredicate,
        object_entity_id: str,
        memory_id: str | None = None,
        confidence: float = 1.0,
        metadata: dict | None = None,
    ) -> GraphRelation:
        now = _utc_now()
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT relation_id FROM kg_relations
                WHERE user_id = ? AND subject_entity_id = ? AND predicate = ?
                  AND object_entity_id = ? AND COALESCE(memory_id, '') = COALESCE(?, '')
                """,
                (user_id, subject_entity_id, predicate.value, object_entity_id, memory_id),
            ).fetchone()
            if row:
                relation_id = row["relation_id"]
                conn.execute(
                    """
                    UPDATE kg_relations
                    SET confidence = ?, metadata_json = ?
                    WHERE relation_id = ?
                    """,
                    (confidence, json.dumps(metadata or {}), relation_id),
                )
            else:
                relation_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO kg_relations (
                        relation_id, user_id, subject_entity_id, predicate, object_entity_id,
                        memory_id, confidence, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relation_id,
                        user_id,
                        subject_entity_id,
                        predicate.value,
                        object_entity_id,
                        memory_id,
                        confidence,
                        json.dumps(metadata or {}),
                        now,
                    ),
                )
        rel = self.get_relation(relation_id, user_id=user_id)
        assert rel is not None
        return rel

    def get_relation(self, relation_id: str, *, user_id: str) -> GraphRelation | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM kg_relations WHERE relation_id = ? AND user_id = ?",
                (relation_id, user_id),
            ).fetchone()
        return _row_to_relation(row) if row else None

    def list_relations_for_entity(
        self,
        entity_id: str,
        *,
        user_id: str,
        direction: str = "both",
    ) -> list[GraphRelation]:
        relations: list[GraphRelation] = []
        with get_connection(self._settings) as conn:
            if direction in ("outgoing", "both"):
                rows = conn.execute(
                    """
                    SELECT * FROM kg_relations
                    WHERE user_id = ? AND subject_entity_id = ?
                    ORDER BY created_at DESC
                    """,
                    (user_id, entity_id),
                ).fetchall()
                relations.extend(_row_to_relation(row) for row in rows)
            if direction in ("incoming", "both"):
                rows = conn.execute(
                    """
                    SELECT * FROM kg_relations
                    WHERE user_id = ? AND object_entity_id = ?
                    ORDER BY created_at DESC
                    """,
                    (user_id, entity_id),
                ).fetchall()
                relations.extend(_row_to_relation(row) for row in rows)
        return relations

    def link_memory_entity(self, link: MemoryEntityLink, *, user_id: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO kg_memory_entities (
                    memory_id, entity_id, user_id, mention_context, start_time, end_time, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id, entity_id) DO UPDATE SET
                    mention_context=excluded.mention_context,
                    start_time=excluded.start_time,
                    end_time=excluded.end_time,
                    confidence=excluded.confidence
                """,
                (
                    link.memory_id,
                    link.entity_id,
                    user_id,
                    link.mention_context,
                    link.start_time,
                    link.end_time,
                    link.confidence,
                ),
            )

    def list_memory_entities(self, memory_id: str, *, user_id: str) -> list[GraphEntity]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT e.* FROM kg_entities e
                JOIN kg_memory_entities me ON me.entity_id = e.entity_id
                WHERE me.memory_id = ? AND me.user_id = ?
                ORDER BY e.entity_type, e.name
                """,
                (memory_id, user_id),
            ).fetchall()
        return [_row_to_entity(row) for row in rows]

    def neighbors(
        self,
        entity_id: str,
        *,
        user_id: str,
        depth: int = 1,
    ) -> GraphQueryResponse:
        if depth < 1:
            depth = 1
        if depth > 2:
            depth = 2
        center = self.get_entity(entity_id, user_id=user_id)
        if not center:
            return GraphQueryResponse()
        seen_entities = {entity_id: center}
        seen_relations: dict[str, GraphRelation] = {}
        neighbors: list[GraphNeighbor] = []
        frontier = {entity_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for eid in frontier:
                for rel in self.list_relations_for_entity(eid, user_id=user_id, direction="both"):
                    seen_relations[rel.relation_id] = rel
                    other_id = (
                        rel.object_entity_id
                        if rel.subject_entity_id == eid
                        else rel.subject_entity_id
                    )
                    direction = "outgoing" if rel.subject_entity_id == eid else "incoming"
                    other = self.get_entity(other_id, user_id=user_id)
                    if not other:
                        continue
                    seen_entities[other_id] = other
                    neighbors.append(
                        GraphNeighbor(entity=other, relation=rel, direction=direction)
                    )
                    next_frontier.add(other_id)
            frontier = next_frontier - set(seen_entities.keys())

        return GraphQueryResponse(
            entities=list(seen_entities.values()),
            relations=list(seen_relations.values()),
            neighbors=neighbors,
        )


_STORES: dict[str, KnowledgeGraphStore] = {}


def get_knowledge_graph_store(settings: Settings | None = None) -> KnowledgeGraphStore:
    settings = settings or get_settings()
    key = settings.sqlite_path
    if key not in _STORES:
        _STORES[key] = KnowledgeGraphStore(settings)
    return _STORES[key]


def reset_knowledge_graph_store_cache() -> None:
    _STORES.clear()


def _row_to_entity(row) -> GraphEntity:
    return GraphEntity(
        entity_id=row["entity_id"],
        user_id=row["user_id"],
        entity_type=EntityType(row["entity_type"]),
        name=row["name"],
        normalized_name=row["normalized_name"],
        aliases=json.loads(row["aliases_json"] or "[]"),
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_relation(row) -> GraphRelation:
    return GraphRelation(
        relation_id=row["relation_id"],
        user_id=row["user_id"],
        subject_entity_id=row["subject_entity_id"],
        predicate=RelationPredicate(row["predicate"]),
        object_entity_id=row["object_entity_id"],
        memory_id=row["memory_id"],
        confidence=float(row["confidence"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
    )

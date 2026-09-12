"""Safe, idempotent SQLite to Postgres migration for the knowledge graph."""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.knowledge_graph_store import _validate_temporal_window, normalize_entity_name
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.models.knowledge_graph import EntityType, RelationPredicate


@dataclass(frozen=True)
class KnowledgeGraphMigrationPreview:
    entities: int
    relations: int
    memory_links: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeGraphMigrationReport:
    entities_seen: int
    entities_inserted: int
    entities_skipped_existing: int
    relations_seen: int
    relations_inserted: int
    relations_skipped_existing: int
    memory_links_seen: int
    memory_links_inserted: int
    memory_links_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_knowledge_graph_migration(
    settings: Settings | None = None, *, user_id: str | None = None
) -> KnowledgeGraphMigrationPreview:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as conn:
        entities = int(conn.execute(f"SELECT COUNT(*) FROM kg_entities{where}", params).fetchone()[0])
        relations = int(conn.execute(f"SELECT COUNT(*) FROM kg_relations{where}", params).fetchone()[0])
        memory_links = int(conn.execute(f"SELECT COUNT(*) FROM kg_memory_entities{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM ("
                f"SELECT user_id FROM kg_entities{where} UNION SELECT user_id FROM kg_relations{where} "
                f"UNION SELECT user_id FROM kg_memory_entities{where})",
                params * 3,
            ).fetchone()[0]
        )
    return KnowledgeGraphMigrationPreview(
        entities=entities, relations=relations, memory_links=memory_links, tenants=tenants
    )


def migrate_knowledge_graph_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> KnowledgeGraphMigrationReport:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresKnowledgeGraphStore(factory)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as source:
        entity_rows = source.execute(
            "SELECT entity_id,user_id,entity_type,name,normalized_name,aliases_json,metadata_json,created_at,updated_at "
            f"FROM kg_entities{where} ORDER BY user_id, entity_type, normalized_name, entity_id",
            params,
        ).fetchall()
        relation_rows = source.execute(
            "SELECT relation_id,user_id,subject_entity_id,predicate,object_entity_id,memory_id,confidence,metadata_json,created_at "
            f"FROM kg_relations{where} ORDER BY user_id, created_at, relation_id",
            params,
        ).fetchall()
        link_rows = source.execute(
            "SELECT memory_id,entity_id,user_id,mention_context,start_time,end_time,confidence "
            f"FROM kg_memory_entities{where} ORDER BY user_id, memory_id, entity_id",
            params,
        ).fetchall()

    entities = _validate_entities(entity_rows)
    entity_owners = {row[0]: row[1] for row in entities}
    relations = _validate_relations(relation_rows, entity_owners)
    links = _validate_links(link_rows, entity_owners)

    existing_entities: set[str] = set()
    existing_relations: set[str] = set()
    existing_links: set[tuple[str, str, str]] = set()
    with factory() as target:
        for row in entities:
            existing = target.execute(
                "SELECT entity_id,user_id,entity_type,name,normalized_name,aliases_json,metadata_json,created_at,updated_at "
                "FROM kg_entities WHERE entity_id=%s",
                (row[0],),
            ).fetchone()
            if existing is not None:
                if _signature(existing, 9) != _signature(row, 9):
                    raise ValueError(f"knowledge graph entity id collision for entity_id={row[0]}")
                existing_entities.add(row[0])
        for row in relations:
            existing = target.execute(
                "SELECT relation_id,user_id,subject_entity_id,predicate,object_entity_id,memory_id,confidence,metadata_json,created_at "
                "FROM kg_relations WHERE relation_id=%s",
                (row[0],),
            ).fetchone()
            if existing is not None:
                if _signature(existing, 9) != _signature(row, 9):
                    raise ValueError(f"knowledge graph relation id collision for relation_id={row[0]}")
                existing_relations.add(row[0])
        for row in links:
            key = (row[2], row[0], row[1])
            existing = target.execute(
                "SELECT memory_id,entity_id,user_id,mention_context,start_time,end_time,confidence "
                "FROM kg_memory_entities WHERE user_id=%s AND memory_id=%s AND entity_id=%s",
                key,
            ).fetchone()
            if existing is not None:
                if _signature(existing, 7) != _signature(row, 7):
                    raise ValueError(
                        f"knowledge graph memory-link collision for user_id={row[2]}, memory_id={row[0]}, entity_id={row[1]}"
                    )
                existing_links.add(key)

        entity_inserted = 0
        relation_inserted = 0
        link_inserted = 0
        for row in entities:
            if row[0] in existing_entities:
                continue
            cur = target.execute(
                "INSERT INTO kg_entities (entity_id,user_id,entity_type,name,normalized_name,aliases_json,metadata_json,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(entity_id) DO NOTHING",
                row,
            )
            entity_inserted += max(int(cur.rowcount or 0), 0)
        for row in relations:
            if row[0] in existing_relations:
                continue
            cur = target.execute(
                "INSERT INTO kg_relations (relation_id,user_id,subject_entity_id,predicate,object_entity_id,memory_id,confidence,metadata_json,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(relation_id) DO NOTHING",
                row,
            )
            relation_inserted += max(int(cur.rowcount or 0), 0)
        for row in links:
            key = (row[2], row[0], row[1])
            if key in existing_links:
                continue
            cur = target.execute(
                "INSERT INTO kg_memory_entities (memory_id,entity_id,user_id,mention_context,start_time,end_time,confidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,memory_id,entity_id) DO NOTHING",
                row,
            )
            link_inserted += max(int(cur.rowcount or 0), 0)

    return KnowledgeGraphMigrationReport(
        entities_seen=len(entities),
        entities_inserted=entity_inserted,
        entities_skipped_existing=len(entities) - entity_inserted,
        relations_seen=len(relations),
        relations_inserted=relation_inserted,
        relations_skipped_existing=len(relations) - relation_inserted,
        memory_links_seen=len(links),
        memory_links_inserted=link_inserted,
        memory_links_skipped_existing=len(links) - link_inserted,
    )


def _validate_entities(rows: list[sqlite3.Row]) -> list[tuple[Any, ...]]:
    seen_ids: set[str] = set()
    seen_identity: set[tuple[str, str, str]] = set()
    normalized: list[tuple[Any, ...]] = []
    for row in rows:
        entity_id = str(row["entity_id"] or "").strip()
        tenant = str(row["user_id"] or "").strip()
        entity_type = str(row["entity_type"] or "").strip()
        name = str(row["name"] or "").strip()
        normalized_name = str(row["normalized_name"] or "").strip()
        if not entity_id or not tenant or not name or not normalized_name:
            raise ValueError("knowledge graph entity contains an invalid identity")
        EntityType(entity_type)
        if normalize_entity_name(name) != normalized_name:
            raise ValueError("knowledge graph entity normalized_name drift")
        if entity_id in seen_ids:
            raise ValueError("knowledge graph source contains duplicate entity_id")
        identity = (tenant, entity_type, normalized_name)
        if identity in seen_identity:
            raise ValueError("knowledge graph source contains duplicate entity identity")
        seen_ids.add(entity_id)
        seen_identity.add(identity)
        aliases = _canonical_json_list(row["aliases_json"], "entity aliases_json")
        metadata = _canonical_json_object(row["metadata_json"], "entity metadata_json")
        created = _utc_datetime(row["created_at"], "entity created_at")
        updated = _utc_datetime(row["updated_at"], "entity updated_at")
        if updated < created:
            raise ValueError("knowledge graph entity updated_at precedes created_at")
        normalized.append((entity_id, tenant, entity_type, name, normalized_name, aliases, metadata, created, updated))
    return normalized


def _validate_relations(rows: list[sqlite3.Row], entity_owners: dict[str, str]) -> list[tuple[Any, ...]]:
    seen_ids: set[str] = set()
    seen_identity: set[tuple[str, str, str, str, str]] = set()
    normalized: list[tuple[Any, ...]] = []
    for row in rows:
        relation_id = str(row["relation_id"] or "").strip()
        tenant = str(row["user_id"] or "").strip()
        subject = str(row["subject_entity_id"] or "").strip()
        predicate = str(row["predicate"] or "").strip()
        obj = str(row["object_entity_id"] or "").strip()
        memory_id = row["memory_id"]
        if memory_id is not None:
            memory_id = str(memory_id).strip() or None
        if not relation_id or not tenant or not subject or not obj:
            raise ValueError("knowledge graph relation contains an invalid identity")
        RelationPredicate(predicate)
        if entity_owners.get(subject) != tenant or entity_owners.get(obj) != tenant:
            raise ValueError("knowledge graph relation references an entity outside its tenant")
        confidence = float(row["confidence"])
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("knowledge graph relation confidence must be between 0 and 1")
        metadata = _canonical_json_object(row["metadata_json"], "relation metadata_json")
        parsed_metadata = json.loads(metadata)
        created = _utc_datetime(row["created_at"], "relation created_at")
        _validate_temporal_window(parsed_metadata.get("valid_from") or created.isoformat(), parsed_metadata.get("valid_to"))
        identity = (tenant, subject, predicate, obj, memory_id or "")
        if relation_id in seen_ids or identity in seen_identity:
            raise ValueError("knowledge graph source contains duplicate relation identity")
        seen_ids.add(relation_id)
        seen_identity.add(identity)
        normalized.append((relation_id, tenant, subject, predicate, obj, memory_id, confidence, metadata, created))
    return normalized


def _validate_links(rows: list[sqlite3.Row], entity_owners: dict[str, str]) -> list[tuple[Any, ...]]:
    seen: set[tuple[str, str, str]] = set()
    normalized: list[tuple[Any, ...]] = []
    for row in rows:
        memory_id = str(row["memory_id"] or "").strip()
        entity_id = str(row["entity_id"] or "").strip()
        tenant = str(row["user_id"] or "").strip()
        if not memory_id or not entity_id or not tenant:
            raise ValueError("knowledge graph memory link contains an invalid identity")
        if entity_owners.get(entity_id) != tenant:
            raise ValueError("knowledge graph memory link references an entity outside its tenant")
        start = _optional_finite(row["start_time"], "memory link start_time")
        end = _optional_finite(row["end_time"], "memory link end_time")
        if start is not None and end is not None and end < start:
            raise ValueError("knowledge graph memory link end_time precedes start_time")
        confidence = float(row["confidence"])
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("knowledge graph memory link confidence must be between 0 and 1")
        key = (tenant, memory_id, entity_id)
        if key in seen:
            raise ValueError("knowledge graph source contains duplicate memory link")
        seen.add(key)
        normalized.append((memory_id, entity_id, tenant, str(row["mention_context"] or ""), start, end, confidence))
    return normalized


def _canonical_json_list(value: Any, field: str) -> str:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"knowledge graph {field} is invalid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"knowledge graph {field} must be a list")
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _canonical_json_object(value: Any, field: str) -> str:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"knowledge graph {field} is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"knowledge graph {field} must be an object")
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _utc_datetime(value: Any, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"knowledge graph {field} is blank")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"knowledge graph {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"knowledge graph {field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _optional_finite(value: Any, field: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"knowledge graph {field} must be finite")
    return number


def _signature(row: Any, size: int) -> tuple[Any, ...]:
    if isinstance(row, tuple):
        values = tuple(row[:size])
    else:
        values = tuple(row.values())[:size] if hasattr(row, "values") else tuple(row)[:size]
    normalized: list[Any] = []
    for value in values:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("target knowledge graph timestamp must include timezone")
            normalized.append(value.astimezone(timezone.utc))
        else:
            normalized.append(value)
    return tuple(normalized)


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _normalize_user_id(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    value = user_id.strip()
    if not value:
        raise ValueError("user_id must not be blank")
    return value


def _tenant_filter(user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    return ("", ()) if user_id is None else (" WHERE user_id = ?", (user_id,))

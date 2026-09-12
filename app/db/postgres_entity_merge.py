"""Atomic tenant-scoped entity merge for the Postgres knowledge graph."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from app.models.knowledge_graph import GraphEntity


@dataclass(frozen=True)
class PostgresEntityMergeStats:
    entity: GraphEntity
    rewired_memory_links: int
    rewired_relations: int
    collapsed_relations: int


def merge_postgres_entities(
    store: PostgresKnowledgeGraphStore,
    *,
    user_id: str,
    target_entity_id: str,
    source_entity_id: str,
) -> PostgresEntityMergeStats:
    """Merge source into target in one Postgres transaction.

    The caller validates entity-type and confirmation policy. This function locks both
    tenant-owned entities, rewires links/relations deterministically, collapses
    duplicate/self relations, updates aliases/evidence metadata, and deletes the source.
    """
    now = datetime.now(timezone.utc)
    rewired_links = 0
    rewired_relations = 0
    collapsed_relations = 0

    with store._connection_factory() as conn:  # selected-store transaction boundary
        locked = conn.execute(
            "SELECT * FROM kg_entities WHERE user_id=%s AND entity_id IN (%s,%s) "
            "ORDER BY entity_id FOR UPDATE",
            (user_id, target_entity_id, source_entity_id),
        ).fetchall()
        by_id = {row["entity_id"]: row for row in locked}
        if target_entity_id not in by_id or source_entity_id not in by_id:
            raise ValueError("entity not found for active user")

        target_row = by_id[target_entity_id]
        source_row = by_id[source_entity_id]

        source_links = conn.execute(
            "SELECT memory_id,mention_context,start_time,end_time,confidence "
            "FROM kg_memory_entities WHERE user_id=%s AND entity_id=%s "
            "ORDER BY memory_id",
            (user_id, source_entity_id),
        ).fetchall()
        for row in source_links:
            conn.execute(
                "INSERT INTO kg_memory_entities "
                "(memory_id,entity_id,user_id,mention_context,start_time,end_time,confidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(user_id,memory_id,entity_id) DO UPDATE SET "
                "mention_context=CASE WHEN EXCLUDED.mention_context<>'' THEN EXCLUDED.mention_context "
                "ELSE kg_memory_entities.mention_context END," 
                "start_time=COALESCE(kg_memory_entities.start_time,EXCLUDED.start_time)," 
                "end_time=COALESCE(kg_memory_entities.end_time,EXCLUDED.end_time)," 
                "confidence=GREATEST(kg_memory_entities.confidence,EXCLUDED.confidence)",
                (
                    row["memory_id"],
                    target_entity_id,
                    user_id,
                    row["mention_context"],
                    row["start_time"],
                    row["end_time"],
                    row["confidence"],
                ),
            )
            rewired_links += 1

        source_relations = conn.execute(
            "SELECT * FROM kg_relations WHERE user_id=%s "
            "AND (subject_entity_id=%s OR object_entity_id=%s) "
            "ORDER BY created_at,relation_id FOR UPDATE",
            (user_id, source_entity_id, source_entity_id),
        ).fetchall()
        for row in source_relations:
            new_subject = (
                target_entity_id
                if row["subject_entity_id"] == source_entity_id
                else row["subject_entity_id"]
            )
            new_object = (
                target_entity_id
                if row["object_entity_id"] == source_entity_id
                else row["object_entity_id"]
            )
            if new_subject == new_object:
                conn.execute(
                    "DELETE FROM kg_relations WHERE relation_id=%s AND user_id=%s",
                    (row["relation_id"], user_id),
                )
                collapsed_relations += 1
                continue

            duplicate = conn.execute(
                "SELECT relation_id,confidence,metadata_json FROM kg_relations "
                "WHERE user_id=%s AND relation_id<>%s AND subject_entity_id=%s "
                "AND predicate=%s AND object_entity_id=%s "
                "AND COALESCE(memory_id,'')=COALESCE(%s,'') "
                "ORDER BY created_at,relation_id LIMIT 1 FOR UPDATE",
                (
                    user_id,
                    row["relation_id"],
                    new_subject,
                    row["predicate"],
                    new_object,
                    row["memory_id"],
                ),
            ).fetchone()
            if duplicate:
                existing_metadata = json.loads(duplicate["metadata_json"] or "{}")
                source_metadata = json.loads(row["metadata_json"] or "{}")
                merged_metadata = dict(source_metadata)
                merged_metadata.update(existing_metadata)
                conn.execute(
                    "UPDATE kg_relations SET confidence=%s,metadata_json=%s "
                    "WHERE relation_id=%s AND user_id=%s",
                    (
                        max(float(duplicate["confidence"]), float(row["confidence"])),
                        json.dumps(merged_metadata, sort_keys=True),
                        duplicate["relation_id"],
                        user_id,
                    ),
                )
                conn.execute(
                    "DELETE FROM kg_relations WHERE relation_id=%s AND user_id=%s",
                    (row["relation_id"], user_id),
                )
                collapsed_relations += 1
            else:
                conn.execute(
                    "UPDATE kg_relations SET subject_entity_id=%s,object_entity_id=%s "
                    "WHERE relation_id=%s AND user_id=%s",
                    (new_subject, new_object, row["relation_id"], user_id),
                )
                rewired_relations += 1

        target_aliases = json.loads(target_row["aliases_json"] or "[]")
        source_aliases = json.loads(source_row["aliases_json"] or "[]")
        merged_aliases = sorted(
            ({*target_aliases, *source_aliases, source_row["name"]} - {target_row["name"]})
        )
        target_metadata = json.loads(target_row["metadata_json"] or "{}")
        source_metadata = json.loads(source_row["metadata_json"] or "{}")
        merged_metadata = dict(source_metadata)
        merged_metadata.update(target_metadata)
        prior_ids = list(merged_metadata.get("merged_entity_ids") or [])
        merged_metadata["merged_entity_ids"] = sorted(
            set(prior_ids + [source_entity_id])
        )
        updated = conn.execute(
            "UPDATE kg_entities SET aliases_json=%s,metadata_json=%s,updated_at=%s "
            "WHERE entity_id=%s AND user_id=%s RETURNING *",
            (
                json.dumps(merged_aliases),
                json.dumps(merged_metadata, sort_keys=True),
                now,
                target_entity_id,
                user_id,
            ),
        ).fetchone()
        conn.execute(
            "DELETE FROM kg_memory_entities WHERE entity_id=%s AND user_id=%s",
            (source_entity_id, user_id),
        )
        conn.execute(
            "DELETE FROM kg_entities WHERE entity_id=%s AND user_id=%s",
            (source_entity_id, user_id),
        )

    from app.db.postgres_knowledge_graph_store import _entity

    return PostgresEntityMergeStats(
        entity=_entity(updated),
        rewired_memory_links=rewired_links,
        rewired_relations=rewired_relations,
        collapsed_relations=collapsed_relations,
    )

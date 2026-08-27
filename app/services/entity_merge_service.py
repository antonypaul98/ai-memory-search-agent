"""Deterministic tenant-scoped knowledge-graph entity merge."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.knowledge_graph_store import KnowledgeGraphStore, get_knowledge_graph_store
from app.db.schema import get_connection
from app.models.knowledge_graph import GraphEntity, GraphEntityMergeResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EntityMergeError(ValueError):
    """Raised when a requested graph-entity merge is invalid."""


class EntityMergeService:
    """Merge duplicate aliases without crossing tenant or entity-type boundaries."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: KnowledgeGraphStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_knowledge_graph_store(self._settings)

    def merge(
        self,
        *,
        user_id: str,
        target_entity_id: str,
        source_entity_id: str,
    ) -> GraphEntityMergeResult:
        if target_entity_id == source_entity_id:
            raise EntityMergeError("source and target entities must be different")

        target = self._store.get_entity(target_entity_id, user_id=user_id)
        source = self._store.get_entity(source_entity_id, user_id=user_id)
        if target is None or source is None:
            raise EntityMergeError("entity not found for active user")
        if target.entity_type != source.entity_type:
            raise EntityMergeError("only entities of the same type can be merged")
        if target.entity_type.value == "memory":
            raise EntityMergeError("memory entities cannot be merged")

        rewired_links = 0
        rewired_relations = 0
        collapsed_relations = 0
        now = _utc_now()

        with get_connection(self._settings) as conn:
            source_links = conn.execute(
                """
                SELECT memory_id, mention_context, start_time, end_time, confidence
                FROM kg_memory_entities
                WHERE user_id = ? AND entity_id = ?
                """,
                (user_id, source_entity_id),
            ).fetchall()
            for row in source_links:
                conn.execute(
                    """
                    INSERT INTO kg_memory_entities (
                        memory_id, entity_id, user_id, mention_context,
                        start_time, end_time, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id, entity_id) DO UPDATE SET
                        mention_context = CASE
                            WHEN excluded.mention_context <> '' THEN excluded.mention_context
                            ELSE kg_memory_entities.mention_context
                        END,
                        start_time = COALESCE(kg_memory_entities.start_time, excluded.start_time),
                        end_time = COALESCE(kg_memory_entities.end_time, excluded.end_time),
                        confidence = MAX(kg_memory_entities.confidence, excluded.confidence)
                    """,
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
                """
                SELECT * FROM kg_relations
                WHERE user_id = ?
                  AND (subject_entity_id = ? OR object_entity_id = ?)
                ORDER BY created_at, relation_id
                """,
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
                        "DELETE FROM kg_relations WHERE relation_id = ? AND user_id = ?",
                        (row["relation_id"], user_id),
                    )
                    collapsed_relations += 1
                    continue

                duplicate = conn.execute(
                    """
                    SELECT relation_id, confidence, metadata_json
                    FROM kg_relations
                    WHERE user_id = ?
                      AND relation_id <> ?
                      AND subject_entity_id = ?
                      AND predicate = ?
                      AND object_entity_id = ?
                      AND COALESCE(memory_id, '') = COALESCE(?, '')
                    ORDER BY created_at, relation_id
                    LIMIT 1
                    """,
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
                        """
                        UPDATE kg_relations
                        SET confidence = ?, metadata_json = ?
                        WHERE relation_id = ? AND user_id = ?
                        """,
                        (
                            max(float(duplicate["confidence"]), float(row["confidence"])),
                            json.dumps(merged_metadata, sort_keys=True),
                            duplicate["relation_id"],
                            user_id,
                        ),
                    )
                    conn.execute(
                        "DELETE FROM kg_relations WHERE relation_id = ? AND user_id = ?",
                        (row["relation_id"], user_id),
                    )
                    collapsed_relations += 1
                else:
                    conn.execute(
                        """
                        UPDATE kg_relations
                        SET subject_entity_id = ?, object_entity_id = ?
                        WHERE relation_id = ? AND user_id = ?
                        """,
                        (new_subject, new_object, row["relation_id"], user_id),
                    )
                    rewired_relations += 1

            merged_aliases = sorted(
                {
                    *target.aliases,
                    *source.aliases,
                    source.name,
                }
                - {target.name}
            )
            merged_metadata = dict(source.metadata)
            merged_metadata.update(target.metadata)
            prior_ids = list(merged_metadata.get("merged_entity_ids") or [])
            merged_metadata["merged_entity_ids"] = sorted(
                set(prior_ids + [source_entity_id])
            )

            conn.execute(
                """
                UPDATE kg_entities
                SET aliases_json = ?, metadata_json = ?, updated_at = ?
                WHERE entity_id = ? AND user_id = ?
                """,
                (
                    json.dumps(merged_aliases),
                    json.dumps(merged_metadata, sort_keys=True),
                    now,
                    target_entity_id,
                    user_id,
                ),
            )
            conn.execute(
                "DELETE FROM kg_memory_entities WHERE entity_id = ? AND user_id = ?",
                (source_entity_id, user_id),
            )
            conn.execute(
                "DELETE FROM kg_entities WHERE entity_id = ? AND user_id = ?",
                (source_entity_id, user_id),
            )

        merged = self._store.get_entity(target_entity_id, user_id=user_id)
        assert merged is not None
        return GraphEntityMergeResult(
            entity=merged,
            merged_source_entity_id=source_entity_id,
            rewired_memory_links=rewired_links,
            rewired_relations=rewired_relations,
            collapsed_relations=collapsed_relations,
        )

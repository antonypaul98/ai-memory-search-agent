"""Knowledge graph service — entity extraction and linking."""

from __future__ import annotations

import re

from app.config import Settings, get_settings
from app.db.knowledge_graph_store import KnowledgeGraphStore, get_knowledge_graph_store
from app.models.capsule import MemoryCapsule
from app.models.knowledge_graph import (
    EntityType,
    GraphEntity,
    GraphQueryResponse,
    MemoryEntityLink,
    RelationPredicate,
)
from app.models.reflection import ReflectionInput, SaveReason
from app.models.universal_memory import UniversalMemory
from app.models.video import VideoMetadata


_TECH_PATTERNS = (
    "docker",
    "kubernetes",
    "python",
    "javascript",
    "typescript",
    "react",
    "postgres",
    "redis",
    "gpu",
    "cpu",
    "ram",
)


class KnowledgeGraphService:
    """Build and query the knowledge graph foundation."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: KnowledgeGraphStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_knowledge_graph_store(self._settings)

    def connect_memory(
        self,
        *,
        memory: UniversalMemory,
        metadata: VideoMetadata,
        capsule: MemoryCapsule,
        reflection: ReflectionInput | None = None,
    ) -> dict[str, int]:
        """Extract entities and relations from a memory; return counts by entity type."""
        user_id = memory.user_id
        counts: dict[str, int] = {}

        memory_entity = self._store.upsert_entity(
            user_id=user_id,
            entity_type=EntityType.MEMORY,
            name=memory.title,
            metadata={"memory_id": memory.memory_id, "external_id": memory.external_id},
            entity_id=f"mem:{memory.memory_id}",
        )
        counts[EntityType.MEMORY.value] = counts.get(EntityType.MEMORY.value, 0) + 1

        creator = self._store.upsert_entity(
            user_id=user_id,
            entity_type=EntityType.CREATOR,
            name=metadata.channel or memory.source_author or "Unknown",
        )
        counts[EntityType.CREATOR.value] = counts.get(EntityType.CREATOR.value, 0) + 1
        self._store.upsert_relation(
            user_id=user_id,
            subject_entity_id=memory_entity.entity_id,
            predicate=RelationPredicate.AUTHORED_BY,
            object_entity_id=creator.entity_id,
            memory_id=memory.memory_id,
        )

        for topic in capsule.topics:
            entity = self._ensure_concept(user_id, topic)
            counts[EntityType.CONCEPT.value] = counts.get(EntityType.CONCEPT.value, 0) + 1
            self._link(memory, entity, mention_context=topic)

        for name in capsule.entities:
            entity = self._classify_and_upsert(user_id, name)
            counts[entity.entity_type.value] = counts.get(entity.entity_type.value, 0) + 1
            self._link(memory, entity, mention_context=name)

        for tool in capsule.tools_or_components:
            entity = self._store.upsert_entity(
                user_id=user_id,
                entity_type=EntityType.TECHNOLOGY,
                name=tool,
            )
            counts[EntityType.TECHNOLOGY.value] = counts.get(EntityType.TECHNOLOGY.value, 0) + 1
            self._link(memory, entity, mention_context=tool)
            self._store.upsert_relation(
                user_id=user_id,
                subject_entity_id=memory_entity.entity_id,
                predicate=RelationPredicate.USES_TECHNOLOGY,
                object_entity_id=entity.entity_id,
                memory_id=memory.memory_id,
            )

        if reflection and reflection.goal:
            project = self._store.upsert_entity(
                user_id=user_id,
                entity_type=EntityType.PROJECT,
                name=reflection.goal,
            )
            counts[EntityType.PROJECT.value] = counts.get(EntityType.PROJECT.value, 0) + 1
            self._store.upsert_relation(
                user_id=user_id,
                subject_entity_id=memory_entity.entity_id,
                predicate=RelationPredicate.PART_OF_PROJECT,
                object_entity_id=project.entity_id,
                memory_id=memory.memory_id,
            )

        if reflection and reflection.save_reason == SaveReason.GOAL and reflection.goal:
            tag = self._store.upsert_entity(
                user_id=user_id,
                entity_type=EntityType.TAG,
                name=reflection.save_reason.value,
            )
            counts[EntityType.TAG.value] = counts.get(EntityType.TAG.value, 0) + 1
            self._link(memory, tag, mention_context=reflection.save_reason.value)

        return counts

    def search_entities(
        self,
        *,
        user_id: str,
        query: str = "",
        entity_type: EntityType | None = None,
        limit: int = 20,
    ) -> list[GraphEntity]:
        return self._store.search_entities(
            user_id=user_id,
            query=query,
            entity_type=entity_type,
            limit=limit,
        )

    def get_entity(self, entity_id: str, *, user_id: str) -> GraphEntity | None:
        return self._store.get_entity(entity_id, user_id=user_id)

    def relations_for_entity(
        self,
        entity_id: str,
        *,
        user_id: str,
        direction: str = "both",
    ) -> GraphQueryResponse:
        entity = self._store.get_entity(entity_id, user_id=user_id)
        if not entity:
            return GraphQueryResponse()
        relations = self._store.list_relations_for_entity(
            entity_id, user_id=user_id, direction=direction
        )
        return GraphQueryResponse(entities=[entity], relations=relations)

    def neighbors(
        self,
        entity_id: str,
        *,
        user_id: str,
        depth: int = 1,
    ) -> GraphQueryResponse:
        return self._store.neighbors(entity_id, user_id=user_id, depth=depth)

    def entities_for_memory(self, memory_id: str, *, user_id: str) -> list[GraphEntity]:
        return self._store.list_memory_entities(memory_id, user_id=user_id)

    def _ensure_concept(self, user_id: str, name: str) -> GraphEntity:
        return self._store.upsert_entity(
            user_id=user_id,
            entity_type=EntityType.CONCEPT,
            name=name,
        )

    def _classify_and_upsert(self, user_id: str, name: str) -> GraphEntity:
        lowered = name.lower()
        if any(t in lowered for t in _TECH_PATTERNS):
            etype = EntityType.TECHNOLOGY
        elif re.search(r"\b(inc|corp|llc|ltd|company)\b", lowered):
            etype = EntityType.COMPANY
        elif name.istitle() and len(name.split()) <= 3:
            etype = EntityType.PERSON
        else:
            etype = EntityType.CONCEPT
        return self._store.upsert_entity(user_id=user_id, entity_type=etype, name=name)

    def _link(
        self,
        memory: UniversalMemory,
        entity: GraphEntity,
        *,
        mention_context: str = "",
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> None:
        self._store.link_memory_entity(
            MemoryEntityLink(
                memory_id=memory.memory_id,
                entity_id=entity.entity_id,
                mention_context=mention_context,
                start_time=start_time,
                end_time=end_time,
            ),
            user_id=memory.user_id,
        )
        memory_entity_id = f"mem:{memory.memory_id}"
        self._store.upsert_relation(
            user_id=memory.user_id,
            subject_entity_id=memory_entity_id,
            predicate=RelationPredicate.MENTIONS,
            object_entity_id=entity.entity_id,
            memory_id=memory.memory_id,
            confidence=0.9,
        )

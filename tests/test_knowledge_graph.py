"""Tests for knowledge graph foundation."""

from unittest.mock import MagicMock

import pytest

from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.db.memory_store import MemoryStore
from app.models.capsule import MemoryCapsule, MemorySection
from app.models.knowledge_graph import EntityType, RelationPredicate
from app.models.lifecycle import MemoryLifecycleState
from app.models.reflection import ReflectionInput, SaveReason
from app.models.universal_memory import MemoryProvenance
from app.models.video import SourceType, VideoMetadata
from app.services.knowledge_graph_service import KnowledgeGraphService


@pytest.fixture
def graph(test_settings) -> KnowledgeGraphService:
    return KnowledgeGraphService(settings=test_settings)


def _memory(store: MemoryStore) -> tuple:
    mem = store.upsert(
        user_id="user-a",
        source_type=SourceType.YOUTUBE,
        external_id="kgvid",
        canonical_url="https://youtu.be/kgvid",
        title="Graph Video",
        source_author="Tech Channel",
        provenance=MemoryProvenance(),
        lifecycle_state=MemoryLifecycleState.ENRICHED,
    )
    metadata = VideoMetadata(
        video_id="kgvid",
        title="Graph Video",
        channel="Tech Channel",
        webpage_url="https://youtu.be/kgvid",
    )
    capsule = MemoryCapsule(
        video_id="kgvid",
        title="Graph Video",
        one_line_memory="Docker setup guide",
        short_summary="How to install Docker on Linux",
        topics=["docker", "linux"],
        entities=["Docker", "Ubuntu"],
        tools_or_components=["Docker", "CPU"],
        procedures=["Install Docker"],
        claims=["Docker simplifies deployment"],
        sections=[
            MemorySection(
                title="Intro",
                summary="Overview of containers",
                start_time=0.0,
                end_time=60.0,
                keywords=["docker"],
            )
        ],
    )
    reflection = ReflectionInput(save_reason=SaveReason.GOAL, goal="Home lab setup")
    return mem, metadata, capsule, reflection


class TestKnowledgeGraph:
    def test_connect_memory_creates_entities_and_relations(
        self, graph: KnowledgeGraphService, test_settings
    ) -> None:
        store = MemoryStore(test_settings)
        memory, metadata, capsule, reflection = _memory(store)
        counts = graph.connect_memory(
            memory=memory,
            metadata=metadata,
            capsule=capsule,
            reflection=reflection,
        )
        assert counts.get(EntityType.CONCEPT.value, 0) >= 2
        assert counts.get(EntityType.TECHNOLOGY.value, 0) >= 1
        assert counts.get(EntityType.PROJECT.value, 0) == 1

        linked = graph.entities_for_memory(memory.memory_id, user_id="user-a")
        assert len(linked) >= 4

        memory_entity = graph.get_entity(f"mem:{memory.memory_id}", user_id="user-a")
        assert memory_entity is not None
        relations = graph.relations_for_entity(
            memory_entity.entity_id, user_id="user-a"
        ).relations
        assert relations
        assert all(rel.valid_from for rel in relations)

    def test_search_entities(self, graph: KnowledgeGraphService, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory, metadata, capsule, reflection = _memory(store)
        graph.connect_memory(memory=memory, metadata=metadata, capsule=capsule, reflection=reflection)
        hits = graph.search_entities(user_id="user-a", query="docker", limit=10)
        assert any("docker" in e.normalized_name for e in hits)

    def test_neighbors_query(self, graph: KnowledgeGraphService, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory, metadata, capsule, reflection = _memory(store)
        graph.connect_memory(memory=memory, metadata=metadata, capsule=capsule, reflection=reflection)
        docker_entities = graph.search_entities(user_id="user-a", query="docker", limit=1)
        assert docker_entities
        response = graph.neighbors(docker_entities[0].entity_id, user_id="user-a", depth=1)
        assert response.neighbors or response.relations

    def test_relation_predicates(self, test_settings) -> None:
        kg_store = KnowledgeGraphStore(test_settings)
        a = kg_store.upsert_entity(user_id="u1", entity_type=EntityType.MEMORY, name="Mem A", entity_id="mem:a")
        b = kg_store.upsert_entity(user_id="u1", entity_type=EntityType.CONCEPT, name="Python")
        rel = kg_store.upsert_relation(
            user_id="u1",
            subject_entity_id=a.entity_id,
            predicate=RelationPredicate.MENTIONS,
            object_entity_id=b.entity_id,
            memory_id="mem-id",
        )
        assert rel.predicate == RelationPredicate.MENTIONS
        # Legacy/default relations are valid from their creation instant.
        assert rel.valid_from == rel.created_at
        assert rel.valid_to is None

    def test_temporal_relation_filters_half_open_window(self, test_settings) -> None:
        kg_store = KnowledgeGraphStore(test_settings)
        a = kg_store.upsert_entity(
            user_id="u1", entity_type=EntityType.MEMORY, name="Temporal Mem", entity_id="mem:t"
        )
        b = kg_store.upsert_entity(
            user_id="u1", entity_type=EntityType.CONCEPT, name="Old Fact"
        )
        rel = kg_store.upsert_relation(
            user_id="u1",
            subject_entity_id=a.entity_id,
            predicate=RelationPredicate.MENTIONS,
            object_entity_id=b.entity_id,
            memory_id="m1",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2026-02-01T00:00:00+00:00",
        )
        assert rel.valid_from == "2026-01-01T00:00:00+00:00"
        assert rel.valid_to == "2026-02-01T00:00:00+00:00"

        before = kg_store.list_relations_for_entity(
            a.entity_id, user_id="u1", at_time="2025-12-31T23:59:59+00:00"
        )
        active = kg_store.list_relations_for_entity(
            a.entity_id, user_id="u1", at_time="2026-01-15T00:00:00+00:00"
        )
        at_end = kg_store.list_relations_for_entity(
            a.entity_id, user_id="u1", at_time="2026-02-01T00:00:00+00:00"
        )
        assert before == []
        assert [item.relation_id for item in active] == [rel.relation_id]
        assert at_end == []

    def test_close_relation_preserves_metadata_and_tenant_scope(self, test_settings) -> None:
        kg_store = KnowledgeGraphStore(test_settings)
        a = kg_store.upsert_entity(
            user_id="u1", entity_type=EntityType.MEMORY, name="Mem", entity_id="mem:close"
        )
        b = kg_store.upsert_entity(
            user_id="u1", entity_type=EntityType.CONCEPT, name="Fact"
        )
        rel = kg_store.upsert_relation(
            user_id="u1",
            subject_entity_id=a.entity_id,
            predicate=RelationPredicate.MENTIONS,
            object_entity_id=b.entity_id,
            metadata={"evidence": "memory:m1"},
            valid_from="2026-01-01T00:00:00+00:00",
        )
        assert kg_store.close_relation(
            rel.relation_id,
            user_id="other-user",
            valid_to="2026-03-01T00:00:00+00:00",
        ) is None

        closed = kg_store.close_relation(
            rel.relation_id,
            user_id="u1",
            valid_to="2026-03-01T00:00:00+00:00",
        )
        assert closed is not None
        assert closed.metadata["evidence"] == "memory:m1"
        assert closed.valid_to == "2026-03-01T00:00:00+00:00"
        assert kg_store.list_relations_for_entity(
            a.entity_id,
            user_id="u1",
            at_time="2026-03-01T00:00:00+00:00",
        ) == []

    def test_rejects_invalid_temporal_window(self, test_settings) -> None:
        kg_store = KnowledgeGraphStore(test_settings)
        a = kg_store.upsert_entity(
            user_id="u1", entity_type=EntityType.MEMORY, name="Mem", entity_id="mem:invalid"
        )
        b = kg_store.upsert_entity(user_id="u1", entity_type=EntityType.CONCEPT, name="Fact")
        with pytest.raises(ValueError, match="valid_to"):
            kg_store.upsert_relation(
                user_id="u1",
                subject_entity_id=a.entity_id,
                predicate=RelationPredicate.MENTIONS,
                object_entity_id=b.entity_id,
                valid_from="2026-02-01T00:00:00+00:00",
                valid_to="2026-01-01T00:00:00+00:00",
            )

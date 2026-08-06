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

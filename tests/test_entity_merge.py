"""Regression tests for deterministic cross-source entity merging."""

from __future__ import annotations

import pytest

from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.models.knowledge_graph import EntityType, MemoryEntityLink, RelationPredicate
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.entity_merge_service import EntityMergeError, EntityMergeService


def test_merge_rewires_links_relations_and_preserves_alias(test_settings) -> None:
    store = KnowledgeGraphStore(test_settings)
    service = EntityMergeService(test_settings, store=store)
    target = store.upsert_entity(
        user_id="u1",
        entity_type=EntityType.COMPANY,
        name="OpenAI",
        aliases=["OpenAI Inc"],
        metadata={"canonical": True},
    )
    source = store.upsert_entity(
        user_id="u1",
        entity_type=EntityType.COMPANY,
        name="Open AI",
        aliases=["Open AI LLC"],
        metadata={"source": "web"},
    )
    memory = store.upsert_entity(
        user_id="u1",
        entity_type=EntityType.MEMORY,
        name="Saved article",
        entity_id="mem:m1",
    )
    store.link_memory_entity(
        MemoryEntityLink(memory_id="m1", entity_id=source.entity_id, mention_context="Open AI"),
        user_id="u1",
    )
    store.upsert_relation(
        user_id="u1",
        subject_entity_id=memory.entity_id,
        predicate=RelationPredicate.MENTIONS,
        object_entity_id=source.entity_id,
        memory_id="m1",
        confidence=0.8,
    )

    result = service.merge(
        user_id="u1",
        target_entity_id=target.entity_id,
        source_entity_id=source.entity_id,
    )

    assert result.entity.entity_id == target.entity_id
    assert "Open AI" in result.entity.aliases
    assert "Open AI LLC" in result.entity.aliases
    assert result.entity.metadata["canonical"] is True
    assert source.entity_id in result.entity.metadata["merged_entity_ids"]
    assert store.get_entity(source.entity_id, user_id="u1") is None
    linked = store.list_memory_entities("m1", user_id="u1")
    assert [item.entity_id for item in linked] == [target.entity_id]
    relations = store.list_relations_for_entity(target.entity_id, user_id="u1")
    assert len(relations) == 1
    assert relations[0].object_entity_id == target.entity_id


def test_merge_collapses_duplicate_relation_and_keeps_best_confidence(test_settings) -> None:
    store = KnowledgeGraphStore(test_settings)
    service = EntityMergeService(test_settings, store=store)
    target = store.upsert_entity(user_id="u1", entity_type=EntityType.TECHNOLOGY, name="PostgreSQL")
    source = store.upsert_entity(user_id="u1", entity_type=EntityType.TECHNOLOGY, name="Postgres")
    memory = store.upsert_entity(
        user_id="u1", entity_type=EntityType.MEMORY, name="DB notes", entity_id="mem:db"
    )
    store.upsert_relation(
        user_id="u1",
        subject_entity_id=memory.entity_id,
        predicate=RelationPredicate.USES_TECHNOLOGY,
        object_entity_id=target.entity_id,
        memory_id="db",
        confidence=0.7,
        metadata={"target": True},
    )
    store.upsert_relation(
        user_id="u1",
        subject_entity_id=memory.entity_id,
        predicate=RelationPredicate.USES_TECHNOLOGY,
        object_entity_id=source.entity_id,
        memory_id="db",
        confidence=0.95,
        metadata={"source": True},
    )

    result = service.merge(
        user_id="u1", target_entity_id=target.entity_id, source_entity_id=source.entity_id
    )
    relations = store.list_relations_for_entity(target.entity_id, user_id="u1")
    assert len(relations) == 1
    assert relations[0].confidence == pytest.approx(0.95)
    assert relations[0].metadata["target"] is True
    assert relations[0].metadata["source"] is True
    assert result.collapsed_relations == 1


def test_merge_is_tenant_scoped_and_same_type_only(test_settings) -> None:
    store = KnowledgeGraphStore(test_settings)
    service = EntityMergeService(test_settings, store=store)
    target = store.upsert_entity(user_id="u1", entity_type=EntityType.COMPANY, name="Acme")
    source_other_tenant = store.upsert_entity(
        user_id="u2", entity_type=EntityType.COMPANY, name="Acme Corp"
    )
    with pytest.raises(EntityMergeError, match="not found"):
        service.merge(
            user_id="u1",
            target_entity_id=target.entity_id,
            source_entity_id=source_other_tenant.entity_id,
        )
    assert store.get_entity(source_other_tenant.entity_id, user_id="u2") is not None

    concept = store.upsert_entity(user_id="u1", entity_type=EntityType.CONCEPT, name="Acme idea")
    with pytest.raises(EntityMergeError, match="same type"):
        service.merge(
            user_id="u1", target_entity_id=target.entity_id, source_entity_id=concept.entity_id
        )


def test_merge_rejects_memory_entities(test_settings) -> None:
    store = KnowledgeGraphStore(test_settings)
    service = EntityMergeService(test_settings, store=store)
    target = store.upsert_entity(
        user_id="u1", entity_type=EntityType.MEMORY, name="One", entity_id="mem:one"
    )
    source = store.upsert_entity(
        user_id="u1", entity_type=EntityType.MEMORY, name="Two", entity_id="mem:two"
    )
    with pytest.raises(EntityMergeError, match="memory entities"):
        service.merge(
            user_id="u1", target_entity_id=target.entity_id, source_entity_id=source.entity_id
        )


def test_merge_api_uses_authenticated_tenant(client, test_settings) -> None:
    store = KnowledgeGraphStore(test_settings)
    target = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.TECHNOLOGY,
        name="Kubernetes",
    )
    source = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.TECHNOLOGY,
        name="K8s",
    )
    response = client.post(
        f"/api/v1/knowledge/entities/{target.entity_id}/merge",
        json={"source_entity_id": source.entity_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entity"]["entity_id"] == target.entity_id
    assert body["merged_source_entity_id"] == source.entity_id
    assert "K8s" in body["entity"]["aliases"]


def test_merge_api_returns_conflict_for_same_entity(client, test_settings) -> None:
    store = KnowledgeGraphStore(test_settings)
    entity = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.CONCEPT,
        name="RAG",
    )
    response = client.post(
        f"/api/v1/knowledge/entities/{entity.entity_id}/merge",
        json={"source_entity_id": entity.entity_id},
    )
    assert response.status_code == 409

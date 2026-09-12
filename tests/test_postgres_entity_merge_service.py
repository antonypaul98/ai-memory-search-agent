from __future__ import annotations

from app.db.postgres_entity_merge import PostgresEntityMergeStats
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from app.models.knowledge_graph import EntityType, GraphEntity
from app.services import entity_merge_service
from app.services.entity_merge_service import EntityMergeService


def _entity(entity_id: str, name: str) -> GraphEntity:
    return GraphEntity(
        entity_id=entity_id,
        user_id="tenant-a",
        entity_type=EntityType.CONCEPT,
        name=name,
        normalized_name=name.lower(),
        aliases=[],
        metadata={},
        created_at="2026-09-12T00:00:00+00:00",
        updated_at="2026-09-12T00:00:00+00:00",
    )


def test_service_routes_postgres_merge_through_atomic_backend(monkeypatch, test_settings):
    target = _entity("target", "Target")
    source = _entity("source", "Source")
    store = object.__new__(PostgresKnowledgeGraphStore)

    def get_entity(entity_id: str, *, user_id: str):
        assert user_id == "tenant-a"
        return {"target": target, "source": source}.get(entity_id)

    store.get_entity = get_entity  # type: ignore[method-assign]
    called = []

    def fake_merge(selected_store, **kwargs):
        assert selected_store is store
        called.append(kwargs)
        return PostgresEntityMergeStats(
            entity=target.model_copy(update={"aliases": ["Source"]}),
            rewired_memory_links=2,
            rewired_relations=3,
            collapsed_relations=1,
        )

    monkeypatch.setattr(entity_merge_service, "merge_postgres_entities", fake_merge)
    result = EntityMergeService(test_settings, store=store).merge(
        user_id="tenant-a",
        target_entity_id="target",
        source_entity_id="source",
    )

    assert called == [
        {
            "user_id": "tenant-a",
            "target_entity_id": "target",
            "source_entity_id": "source",
        }
    ]
    assert result.entity.aliases == ["Source"]
    assert result.rewired_memory_links == 2
    assert result.rewired_relations == 3
    assert result.collapsed_relations == 1

"""Regression tests for F-33 temporal knowledge API behavior."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings, get_health_service
from app.config import Settings, get_settings
from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.db.repositories.memory_repository import MemoryRepository
from app.models.knowledge_graph import EntityType, RelationPredicate
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.services.health_service import HealthService


def _demo_user() -> UserPublic:
    return UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Demo")


@pytest.fixture
def temporal_client(test_settings: Settings) -> TestClient:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = _demo_user
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        settings=test_settings,
        repository=MemoryRepository(test_settings),
    )

    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as client:
            yield client

    app.dependency_overrides.clear()


def _seed_temporal_relation(test_settings: Settings) -> tuple[str, str]:
    store = KnowledgeGraphStore(test_settings)
    subject = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.PROJECT,
        name="Memory Search",
        entity_id="project:memory-search",
    )
    old_state = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.TECHNOLOGY,
        name="SQLite",
    )
    relation = store.upsert_relation(
        user_id=LOCAL_DEFAULT_USER_ID,
        subject_entity_id=subject.entity_id,
        predicate=RelationPredicate.USES_TECHNOLOGY,
        object_entity_id=old_state.entity_id,
        memory_id="evidence-memory-1",
        confidence=0.95,
        metadata={"evidence": "memory:evidence-memory-1"},
        valid_from="2026-01-01T00:00:00+00:00",
        valid_to="2026-06-01T00:00:00+00:00",
    )
    return subject.entity_id, relation.relation_id


class TestTemporalKnowledgeAPI:
    def test_relations_as_of_time_respects_half_open_validity_window(
        self,
        temporal_client: TestClient,
        test_settings: Settings,
    ) -> None:
        entity_id, relation_id = _seed_temporal_relation(test_settings)

        active = temporal_client.get(
            f"/api/v1/knowledge/entities/{entity_id}/relations",
            params={"at": "2026-05-31T23:59:59Z"},
        )
        assert active.status_code == 200
        assert [item["relation_id"] for item in active.json()["relations"]] == [relation_id]
        assert active.json()["relations"][0]["valid_from"] == "2026-01-01T00:00:00+00:00"
        assert active.json()["relations"][0]["valid_to"] == "2026-06-01T00:00:00+00:00"

        expired = temporal_client.get(
            f"/api/v1/knowledge/entities/{entity_id}/relations",
            params={"at": "2026-06-01T00:00:00Z"},
        )
        assert expired.status_code == 200
        assert expired.json()["relations"] == []

    def test_neighbor_as_of_query_does_not_leak_future_or_expired_facts(
        self,
        temporal_client: TestClient,
        test_settings: Settings,
    ) -> None:
        entity_id, relation_id = _seed_temporal_relation(test_settings)

        before = temporal_client.get(
            "/api/v1/knowledge/graph/neighbors",
            params={"entity_id": entity_id, "at": "2025-12-31T23:59:59Z"},
        )
        assert before.status_code == 200
        assert before.json()["relations"] == []
        assert before.json()["neighbors"] == []

        during = temporal_client.get(
            "/api/v1/knowledge/graph/neighbors",
            params={"entity_id": entity_id, "at": "2026-03-01T00:00:00Z"},
        )
        assert during.status_code == 200
        assert [item["relation_id"] for item in during.json()["relations"]] == [relation_id]

    def test_invalid_as_of_timestamp_is_rejected_by_api(
        self,
        temporal_client: TestClient,
        test_settings: Settings,
    ) -> None:
        entity_id, _ = _seed_temporal_relation(test_settings)
        response = temporal_client.get(
            f"/api/v1/knowledge/entities/{entity_id}/relations",
            params={"at": "not-a-date"},
        )
        assert response.status_code == 422

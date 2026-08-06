"""API tests for memories and knowledge graph routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings, get_health_service
from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore
from app.db.repositories.memory_repository import MemoryRepository
from app.models.lifecycle import MemoryLifecycleState
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.models.video import SourceType
from app.services.health_service import HealthService
from app.services.knowledge_graph_service import KnowledgeGraphService


def _demo_user() -> UserPublic:
    return UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Demo")


@pytest.fixture
def brain_client(test_settings: Settings) -> TestClient:
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


class TestBrainAPI:
    def test_memory_by_external_and_lifecycle(self, brain_client: TestClient, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory = store.upsert(
            user_id=LOCAL_DEFAULT_USER_ID,
            source_type=SourceType.YOUTUBE,
            external_id="apivid",
            canonical_url="https://youtu.be/apivid",
            title="API Video",
            lifecycle_state=MemoryLifecycleState.CAPTURED,
        )
        store.update_lifecycle_state(
            memory_id=memory.memory_id,
            user_id=LOCAL_DEFAULT_USER_ID,
            to_state=MemoryLifecycleState.PARSED,
            reason="test",
        )

        resp = brain_client.get(
            "/api/v1/memories/by-external",
            params={"source_type": "youtube", "external_id": "apivid"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Video"

        life = brain_client.get(f"/api/v1/memories/{memory.memory_id}/lifecycle")
        assert life.status_code == 200
        assert len(life.json()) >= 1

    def test_knowledge_entity_search(self, brain_client: TestClient, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory = store.upsert(
            user_id=LOCAL_DEFAULT_USER_ID,
            source_type=SourceType.YOUTUBE,
            external_id="kgapi",
            canonical_url="https://youtu.be/kgapi",
            title="KG API",
        )
        from app.models.capsule import MemoryCapsule
        from app.models.video import VideoMetadata

        graph = KnowledgeGraphService(settings=test_settings)
        graph.connect_memory(
            memory=memory,
            metadata=VideoMetadata(
                video_id="kgapi",
                title="KG API",
                channel="Chan",
                webpage_url="https://youtu.be/kgapi",
            ),
            capsule=MemoryCapsule(
                video_id="kgapi",
                title="KG API",
                one_line_memory="x",
                short_summary="y",
                topics=["kubernetes"],
                entities=[],
                tools_or_components=[],
                procedures=[],
                claims=[],
            ),
            reflection=None,
        )

        resp = brain_client.get("/api/v1/knowledge/entities", params={"q": "kubernetes"})
        assert resp.status_code == 200
        assert any("kubernetes" in item["normalized_name"] for item in resp.json())

    def test_archive_memory(self, brain_client: TestClient, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory = store.upsert(
            user_id=LOCAL_DEFAULT_USER_ID,
            source_type=SourceType.YOUTUBE,
            external_id="archapi",
            canonical_url="https://youtu.be/archapi",
            title="Archive",
            lifecycle_state=MemoryLifecycleState.VERIFIED,
        )
        resp = brain_client.post(f"/api/v1/memories/{memory.memory_id}/archive")
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "archived"

    def test_memory_trust_endpoint(self, brain_client: TestClient, test_settings) -> None:
        from app.models.trust import TrustMetrics, TrustTier

        store = MemoryStore(test_settings)
        memory = store.upsert(
            user_id=LOCAL_DEFAULT_USER_ID,
            source_type=SourceType.YOUTUBE,
            external_id="trustapi",
            canonical_url="https://youtu.be/trustapi",
            title="Trust API",
            trust=TrustMetrics(
                source_reliability=0.8,
                freshness=0.9,
                verification=0.85,
                evidence_strength=0.7,
                confidence=0.8,
                overall=0.8,
                tier=TrustTier.TRUSTED,
                computed_at="2026-07-21T00:00:00+00:00",
            ),
        )
        resp = brain_client.get(f"/api/v1/memories/{memory.memory_id}/trust")
        assert resp.status_code == 200
        assert resp.json()["overall"] == 0.8

    def test_memory_entities_endpoint(self, brain_client: TestClient, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory = store.upsert(
            user_id=LOCAL_DEFAULT_USER_ID,
            source_type=SourceType.YOUTUBE,
            external_id="entapi",
            canonical_url="https://youtu.be/entapi",
            title="Entity API",
        )
        from app.models.capsule import MemoryCapsule
        from app.models.video import VideoMetadata

        graph = KnowledgeGraphService(settings=test_settings)
        graph.connect_memory(
            memory=memory,
            metadata=VideoMetadata(
                video_id="entapi",
                title="Entity API",
                channel="Chan",
                webpage_url="https://youtu.be/entapi",
            ),
            capsule=MemoryCapsule(
                video_id="entapi",
                title="Entity API",
                one_line_memory="x",
                short_summary="y",
                topics=["rust"],
                entities=[],
                tools_or_components=[],
                procedures=[],
                claims=[],
            ),
            reflection=None,
        )
        resp = brain_client.get(f"/api/v1/knowledge/memories/{memory.memory_id}/entities")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

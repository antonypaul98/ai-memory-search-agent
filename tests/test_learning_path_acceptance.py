"""Acceptance coverage for V1-13 Learning Path Generator.

The learning path is a read-only, deterministic projection of saved evidence. It must
never invent external learning material and must always remain tenant scoped.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import auth as auth_mod
from app.api.routes import intelligence as intelligence_routes
from app.config import Settings
from app.main import app
from app.models.intelligence import LearningRoadmap
from app.models.user import UserPublic
from app.services.memory_intelligence_service import MemoryIntelligenceService


def _settings(tmp_path) -> Settings:
    return Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="learning_path_acceptance",
        sqlite_path=str(tmp_path / "memory.db"),
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        auth_enabled=False,
        local_demo_mode=True,
        debug=True,
    )


def test_missing_topic_returns_grounded_gap_without_fabricated_steps(tmp_path) -> None:
    service = MemoryIntelligenceService(settings=_settings(tmp_path))

    roadmap = service.roadmap("Never Saved Topic", user_id="tenant-a")

    assert roadmap.evidence_only is True
    assert roadmap.beginner == []
    assert roadmap.intermediate == []
    assert roadmap.advanced == []
    assert roadmap.recommended_order == []
    assert roadmap.already_completed == []
    assert roadmap.suggested_next == []
    assert roadmap.missing_prerequisites == [
        "No saved memories found for 'Never Saved Topic'."
    ]


def test_learning_path_api_forwards_only_authenticated_tenant(tmp_path) -> None:
    seen: list[tuple[str, str]] = []

    class FakeIntelligenceService:
        def roadmap(self, topic: str, *, user_id: str) -> LearningRoadmap:
            seen.append((topic, user_id))
            return LearningRoadmap(topic=topic, evidence_only=True)

    user = UserPublic(user_id="tenant-learning-path", display_name="Learning User")
    app.dependency_overrides[auth_mod.get_current_user] = lambda: user
    app.dependency_overrides[intelligence_routes._intel] = lambda: FakeIntelligenceService()

    try:
        response = TestClient(app).get(
            "/api/v1/intelligence/roadmap", params={"topic": "RAG"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["topic"] == "RAG"
    assert response.json()["evidence_only"] is True
    assert seen == [("RAG", "tenant-learning-path")]
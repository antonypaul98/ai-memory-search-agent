"""
Pytest fixtures shared across the test suite.

Uses temporary Chroma directories so tests never touch ./data/chroma in the repo.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core.embeddings import reset_embedding_model
from app.db.chroma_client import reset_chroma_cache
from app.db.knowledge_graph_store import reset_knowledge_graph_store_cache
from app.db.memory_store import reset_memory_store_cache
from app.db.video_registry import reset_video_registry_cache
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.services.ingest_service import clear_transcript_cache
from app.services.job_worker import stop_job_worker
from app.services.sources import reset_connector_registry_cache
from app.services.command_router import reset_confirm_token_state
from app.core.rate_limit import reset_rate_limiter


def _clear_app_dependency_overrides() -> None:
    try:
        from app.main import app

        app.dependency_overrides.clear()
    except Exception:
        pass


def _demo_user() -> UserPublic:
    return UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Local Demo User")


@pytest.fixture(autouse=True)
def isolated_test_state() -> None:
    """Reset process-wide singletons before and after every test."""
    stop_job_worker()
    get_settings.cache_clear()
    reset_chroma_cache()
    reset_video_registry_cache()
    reset_memory_store_cache()
    reset_knowledge_graph_store_cache()
    clear_transcript_cache()
    reset_embedding_model()
    reset_connector_registry_cache()
    reset_confirm_token_state()
    reset_rate_limiter()
    _clear_app_dependency_overrides()
    yield
    stop_job_worker()
    get_settings.cache_clear()
    reset_chroma_cache()
    reset_video_registry_cache()
    reset_memory_store_cache()
    reset_knowledge_graph_store_cache()
    clear_transcript_cache()
    reset_embedding_model()
    reset_connector_registry_cache()
    reset_confirm_token_state()
    reset_rate_limiter()
    _clear_app_dependency_overrides()


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Settings pointing Chroma storage at an isolated temp directory."""
    chroma_dir = tmp_path / "chroma"
    return Settings(
        app_name="AI Memory Search Agent (test)",
        chroma_persist_dir=str(chroma_dir),
        chroma_collection_name="test_memory_items",
        sqlite_path=str(tmp_path / "videos.db"),
        debug=True,
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        pwa_enabled=True,
        auth_enabled=False,
        local_demo_mode=True,
        rate_limit_enabled=False,
    )


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """FastAPI TestClient with settings and Chroma cache reset for isolation."""
    from app.api.auth import get_current_user
    from app.api.dependencies import get_app_settings, get_health_service
    from app.db.repositories.memory_repository import MemoryRepository
    from app.main import app
    from app.services.health_service import HealthService

    def _override_settings() -> Settings:
        return test_settings

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_app_settings] = _override_settings
    app.dependency_overrides[get_current_user] = _demo_user
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        settings=test_settings,
        repository=MemoryRepository(test_settings),
    )

    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as test_client:
            yield test_client

    app.dependency_overrides.clear()

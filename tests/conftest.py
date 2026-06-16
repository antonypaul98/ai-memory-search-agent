"""
Pytest fixtures shared across the test suite.

Uses temporary Chroma directories so tests never touch ./data/chroma in the repo.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.chroma_client import reset_chroma_cache
from app.main import app


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Settings pointing Chroma storage at an isolated temp directory."""
    chroma_dir = tmp_path / "chroma"
    return Settings(
        app_name="AI Memory Search Agent (test)",
        chroma_persist_dir=str(chroma_dir),
        chroma_collection_name="test_memory_items",
        debug=True,
    )


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """
    FastAPI TestClient with settings and Chroma cache reset for isolation.

    Clears lru_cache on get_settings and get_chroma_client before each test.
    """
    get_settings.cache_clear()
    reset_chroma_cache()
    get_settings.cache_clear()

    # Monkeypatch: override get_settings for this test client session.
    original_get_settings = get_settings

    def _override_settings() -> Settings:
        return test_settings

    app.dependency_overrides[get_settings] = _override_settings

    # Health route uses get_health_service which calls get_settings internally.
    # Patch at module level via cache clear + re-import won't work easily.
    # Instead, override get_health_service to inject test settings.
    from app.api.dependencies import get_health_service
    from app.db.repositories.memory_repository import MemoryRepository
    from app.services.health_service import HealthService

    def _override_health_service() -> HealthService:
        return HealthService(
            settings=test_settings,
            repository=MemoryRepository(test_settings),
        )

    app.dependency_overrides[get_health_service] = _override_health_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_chroma_cache()
    # Restore original cached settings behavior
    original_get_settings.cache_clear()

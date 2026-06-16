"""
FastAPI dependency injection helpers.

Dependencies wire settings and services into route handlers.
Routes stay thin — they never construct repositories or Chroma clients directly.
"""

from app.config import Settings, get_settings
from app.db.repositories.memory_repository import MemoryRepository
from app.services.health_service import HealthService


def get_app_settings() -> Settings:
    """Provide Settings to route handlers via FastAPI Depends()."""
    return get_settings()


def get_memory_repository(settings: Settings | None = None) -> MemoryRepository:
    """Provide MemoryRepository — used by services, not routes directly."""
    resolved = settings or get_settings()
    return MemoryRepository(resolved)


def get_health_service() -> HealthService:
    """Provide HealthService for the health check route."""
    settings = get_settings()
    return HealthService(settings=settings, repository=MemoryRepository(settings))

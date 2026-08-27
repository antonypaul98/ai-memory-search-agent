"""
FastAPI dependency injection helpers.

Dependencies wire settings and services into route handlers.
Routes stay thin — they never construct repositories or Chroma clients directly.
"""

from app.config import Settings, get_settings
from app.db.repositories.memory_repository import MemoryRepository
from app.services.chat_service import ChatService
from app.services.context_router import ContextRouter, LocalMemoryContextProvider
from app.services.health_service import HealthService
from app.services.ingest_service import IngestService
from app.services.model_router import ModelRouter
from app.services.recommendation_service import RecommendationService
from app.services.search_service import SearchService


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


def get_ingest_service() -> IngestService:
    """Provide IngestService for video ingest routes."""
    settings = get_settings()
    return IngestService(
        settings=settings,
        repository=MemoryRepository(settings),
    )


def get_search_service() -> SearchService:
    """Provide SearchService for search routes."""
    settings = get_settings()
    return SearchService(
        settings=settings,
        repository=MemoryRepository(settings),
    )


def get_context_router() -> ContextRouter:
    """Provide the provider-neutral context router with local AHME as provider zero."""
    search_service = get_search_service()
    return ContextRouter([LocalMemoryContextProvider(search_service)])


def get_model_router() -> ModelRouter:
    """Provide the model router over operator-configured/BYO provider credentials."""
    return ModelRouter(get_settings())


def get_chat_service() -> ChatService:
    """Provide ChatService for chat routes."""
    settings = get_settings()
    return ChatService(
        settings=settings,
        repository=MemoryRepository(settings),
    )


def get_recommendation_service() -> RecommendationService:
    """Provide RecommendationService for recommendation routes."""
    settings = get_settings()
    repository = MemoryRepository(settings)
    return RecommendationService(settings=settings, repository=repository)

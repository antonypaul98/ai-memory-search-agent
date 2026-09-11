"""
FastAPI dependency injection helpers.

Dependencies wire settings and services into route handlers.
Routes stay thin — they never construct repositories or Chroma clients directly.
"""

from app.config import Settings, get_settings
from app.db.postgres_home_physical_memory_store import PostgresHomePhysicalMemoryStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.repositories.memory_repository import MemoryRepository
from app.services.adaptive_model_router import AdaptiveModelRouter
from app.services.chat_service import ChatService
from app.services.context_router import ContextRouter, LocalMemoryContextProvider
from app.services.feedback_service import FeedbackService
from app.services.health_service import HealthService
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import BoundedVisionCaptureService
from app.services.home_agent.observation_ingest import HomeObservationIngestService
from app.services.home_agent.query_service import HomeAgentQueryService
from app.services.home_agent.vision_adapter import ConsentGatedVisionAdapter
from app.services.ingest_service import IngestService
from app.services.recommendation_service import RecommendationService
from app.services.search_service import SearchService


_HOME_AGENT_CAPTURE_REGISTRY = CaptureSessionRegistry()


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


def get_feedback_service() -> FeedbackService:
    """Provide deterministic feedback/reward storage and learned output preferences."""
    return FeedbackService(get_settings())


def get_model_router() -> AdaptiveModelRouter:
    """Provide model routing with token-efficient, feedback-aware output adaptation."""
    settings = get_settings()
    return AdaptiveModelRouter(settings, feedback_service=FeedbackService(settings))


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


def _get_home_agent_physical_memory_store() -> PostgresHomePhysicalMemoryStore:
    settings = get_settings()
    connection_factory = get_postgres_connection_factory(settings)
    return PostgresHomePhysicalMemoryStore(connection_factory)


def get_home_agent_query_service() -> HomeAgentQueryService:
    """Provide the persistent Home Agent physical-memory query service."""
    return HomeAgentQueryService(_get_home_agent_physical_memory_store())


def get_home_agent_capture_service() -> BoundedVisionCaptureService:
    """Provide bounded, consent-gated Home Agent vision capture control."""
    ingest_service = HomeObservationIngestService(_get_home_agent_physical_memory_store())
    adapter = ConsentGatedVisionAdapter(ingest_service)
    return BoundedVisionCaptureService(adapter)


def get_home_agent_capture_registry() -> CaptureSessionRegistry:
    """Provide the process-local server-owned capture-session registry."""
    return _HOME_AGENT_CAPTURE_REGISTRY

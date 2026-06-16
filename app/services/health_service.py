"""
Health check business logic.

Keeps the health route thin: route → service → repository → Chroma.
"""

from app.config import Settings, get_settings
from app.db.repositories.memory_repository import MemoryRepository
from app.models.health import ChromaHealthDetail, HealthResponse


class HealthService:
    """Build the health status response for GET /api/v1/health."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: MemoryRepository | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or MemoryRepository(self._settings)

    def get_health_status(self) -> HealthResponse:
        """
        Check application and ChromaDB health.

        Raises ChromaConnectionError if Chroma is unreachable (→ HTTP 503).
        """
        chroma_info = self._repository.check_connection()
        return HealthResponse(
            status="ok",
            app_name=self._settings.app_name,
            chroma=ChromaHealthDetail(**chroma_info),
        )

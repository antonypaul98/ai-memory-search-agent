"""
Health check business logic.

Keeps the health route thin: route → service → repositories/dependencies.
"""

from app.config import Settings, get_settings
from app.core.exceptions import DependencyReadinessError
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import is_complete_postgres_profile
from app.db.repositories.memory_repository import MemoryRepository
from app.models.health import ChromaHealthDetail, HealthResponse


class HealthService:
    """Build the health status response for readiness/health endpoints."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: MemoryRepository | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or MemoryRepository(self._settings)

    def _check_relational_readiness(self) -> None:
        """Require a live Postgres connection only for the complete production profile."""
        if not is_complete_postgres_profile(self._settings):
            return
        try:
            connection_factory = get_postgres_connection_factory(self._settings)
            with connection_factory() as conn:
                row = conn.execute("SELECT 1 AS ready").fetchone()
            if not row:
                raise DependencyReadinessError("Postgres is not ready")
        except DependencyReadinessError:
            raise
        except Exception as exc:
            # Keep credentials, DSNs, hostnames, and driver details out of health responses.
            raise DependencyReadinessError("Postgres is not ready") from exc

    def get_health_status(self) -> HealthResponse:
        """
        Check required application storage dependencies.

        Local/self-host profiles retain the existing Chroma-only readiness behavior.
        A complete production Postgres profile additionally requires a successful
        relational probe. Liveness remains a separate dependency-free endpoint.
        """
        chroma_info = self._repository.check_connection()
        self._check_relational_readiness()
        return HealthResponse(
            status="ok",
            app_name=self._settings.app_name,
            chroma=ChromaHealthDetail(**chroma_info),
        )

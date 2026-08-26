"""
Health and lightweight observability routes.

GET /api/v1/health — verifies the API and ChromaDB are running.
GET /api/v1/metrics — process-local request counters for single-node ops.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_health_service
from app.core.exceptions import ChromaConnectionError
from app.middleware.observability import metrics_snapshot
from app.models.health import HealthResponse
from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """
    Return application health including ChromaDB connection status.

    Returns 503 if ChromaDB cannot be reached.
    """
    try:
        return service.get_health_status()
    except ChromaConnectionError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc


@router.get("/metrics")
def request_metrics() -> dict[str, object]:
    """Return process-local HTTP counters for the single-node deployment profile."""
    return metrics_snapshot()

"""
Health check route.

GET /api/v1/health — verifies the API and ChromaDB are running.

Flow: route → HealthService → MemoryRepository → Chroma
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_health_service
from app.core.exceptions import ChromaConnectionError
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

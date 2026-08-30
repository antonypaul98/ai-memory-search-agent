"""
Health and lightweight observability routes.

GET /api/v1/live — process liveness; no external dependency checks.
GET /api/v1/ready — dependency readiness; verifies ChromaDB is reachable.
GET /api/v1/health — backward-compatible alias for readiness.
GET /api/v1/metrics — Prometheus text exposition for single-node ops.
GET /api/v1/metrics.json — backward-compatible process-local JSON snapshot.
"""

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.dependencies import get_health_service
from app.core.exceptions import ChromaConnectionError
from app.middleware.observability import metrics_snapshot, prometheus_metrics_text
from app.models.health import HealthResponse
from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/live")
def liveness_check() -> dict[str, str]:
    """Return process liveness without touching heavyweight dependencies."""
    return {"status": "ok"}


def _dependency_health(service: HealthService) -> HealthResponse:
    try:
        return service.get_health_status()
    except ChromaConnectionError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc


@router.get("/ready", response_model=HealthResponse)
def readiness_check(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """Return readiness only when required storage dependencies are reachable."""
    return _dependency_health(service)


@router.get("/health", response_model=HealthResponse)
def health_check(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """Backward-compatible readiness endpoint retained for existing clients."""
    return _dependency_health(service)


@router.get("/metrics", response_class=Response)
def request_metrics() -> Response:
    """Return privacy-safe Prometheus text exposition for local scraping."""
    return Response(
        content=prometheus_metrics_text(),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/metrics.json")
def request_metrics_json() -> dict[str, object]:
    """Retain the original JSON snapshot for existing local consumers."""
    return metrics_snapshot()

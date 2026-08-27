"""Model router API: auto-select a configured model or honor an explicit user pin."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_model_router
from app.models.model_router import ModelCatalogResponse, ModelRouteRequest, ModelRouteResponse
from app.models.user import UserPublic
from app.services.model_router import ModelRouteError, ModelRouter

router = APIRouter(tags=["models"])


@router.post("/models/route", response_model=ModelRouteResponse)
def route_model(
    request: ModelRouteRequest,
    router_service: ModelRouter = Depends(get_model_router),
    user: UserPublic = Depends(get_current_user),
) -> ModelRouteResponse:
    try:
        return router_service.route(request, user_id=user.user_id)
    except ModelRouteError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/models/catalog", response_model=ModelCatalogResponse)
def model_catalog(
    router_service: ModelRouter = Depends(get_model_router),
    user: UserPublic = Depends(get_current_user),
) -> ModelCatalogResponse:
    return router_service.catalog(user_id=user.user_id)

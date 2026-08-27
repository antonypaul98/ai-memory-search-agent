"""Provider-neutral context routing API."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_context_router
from app.models.context import ContextPacket, ContextRequest
from app.models.user import UserPublic
from app.services.context_router import ContextRouter

router = APIRouter(tags=["context"])


@router.post("/context/route", response_model=ContextPacket)
def route_context(
    request: ContextRequest,
    router_service: ContextRouter = Depends(get_context_router),
    user: UserPublic = Depends(get_current_user),
) -> ContextPacket:
    """Build the smallest policy-compliant context packet for the requested task."""
    if not request.task.strip():
        raise HTTPException(status_code=400, detail="Context task cannot be empty.")
    try:
        return router_service.route(request, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

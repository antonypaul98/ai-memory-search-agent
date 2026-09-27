"""Authenticated Jarvis V1 entry point."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings
from app.models.jarvis import JarvisRequest, JarvisResponse
from app.models.user import UserPublic
from app.services.jarvis_core_runtime import JarvisCoreRuntime

router = APIRouter(prefix="/jarvis", tags=["jarvis"])


@router.post("/run", response_model=JarvisResponse)
def run_jarvis(
    body: JarvisRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> JarvisResponse:
    """Plan and execute one safe Jarvis turn for the authenticated tenant."""
    try:
        return JarvisCoreRuntime(settings).run(user_id=user.user_id, request=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

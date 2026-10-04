"""Authenticated Jarvis V1 entry point."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings, get_home_agent_query_service
from app.config import Settings
from app.models.jarvis import JarvisRequest, JarvisResponse, JarvisVoiceRequest
from app.models.user import UserPublic
from app.api.routes.home_agent_query import (
    NaturalLanguageQueryRequest, NaturalLanguageQueryResponse, natural_language_query,
)
from app.services.home_agent.query_service import HomeAgentQueryService
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


@router.post("/voice", response_model=JarvisResponse)
def run_jarvis_voice(
    body: JarvisVoiceRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> JarvisResponse:
    """Execute a bounded voice transcript through the same tenant-bound runtime."""
    try:
        return JarvisCoreRuntime(settings).run(
            user_id=user.user_id,
            request=body.to_jarvis_request(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/home", response_model=NaturalLanguageQueryResponse)
def query_jarvis_home(
    body: NaturalLanguageQueryRequest,
    user: UserPublic = Depends(get_current_user),
    service: HomeAgentQueryService = Depends(get_home_agent_query_service),
) -> NaturalLanguageQueryResponse:
    """Read existing physical memory; this boundary never opens a camera or writes."""
    return natural_language_query(body=body, service=service, user=user)

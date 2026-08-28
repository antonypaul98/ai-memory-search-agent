"""Read-only audit/event routes for the Memory Search Agent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings
from app.models.event import MemoryEventListResponse, MemoryEventMetricsResponse
from app.models.user import UserPublic
from app.services.event_bus import EventBus

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=MemoryEventListResponse)
def list_events(
    event_type: str | None = Query(default=None, min_length=1, max_length=120),
    request_id: str | None = Query(default=None, min_length=1, max_length=120),
    after_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> MemoryEventListResponse:
    events, next_after_id = EventBus(settings).list_events(
        user_id=user.user_id,
        event_type=event_type,
        request_id=request_id,
        after_id=after_id,
        limit=limit,
    )
    return MemoryEventListResponse(events=events, next_after_id=next_after_id)


@router.get("/metrics", response_model=MemoryEventMetricsResponse)
def event_metrics(
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> MemoryEventMetricsResponse:
    return MemoryEventMetricsResponse(counts=EventBus(settings).metrics(user_id=user.user_id))

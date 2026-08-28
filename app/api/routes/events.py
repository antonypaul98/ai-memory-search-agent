"""Audit/event and opt-in webhook subscription routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings
from app.core.exceptions import AppError
from app.models.event import (
    MemoryEventListResponse,
    MemoryEventMetricsResponse,
    WebhookSubscription,
    WebhookSubscriptionCreate,
    WebhookSubscriptionListResponse,
)
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


@router.post(
    "/webhooks",
    response_model=WebhookSubscription,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook_subscription(
    request: WebhookSubscriptionCreate,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> WebhookSubscription:
    if not request.confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Webhook creation requires explicit confirmation because it enables external delivery.",
        )
    try:
        return EventBus(settings).create_webhook_subscription(
            user_id=user.user_id,
            url=str(request.url),
            event_type=request.event_type,
        )
    except AppError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/webhooks", response_model=WebhookSubscriptionListResponse)
def list_webhook_subscriptions(
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> WebhookSubscriptionListResponse:
    return WebhookSubscriptionListResponse(
        subscriptions=EventBus(settings).list_webhook_subscriptions(user_id=user.user_id)
    )


@router.delete("/webhooks/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook_subscription(
    subscription_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> None:
    deleted = EventBus(settings).delete_webhook_subscription(
        user_id=user.user_id,
        subscription_id=subscription_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")

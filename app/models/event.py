"""Typed domain-event models for the Memory Search audit/event bus."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class MemoryEvent(BaseModel):
    event_id: str
    user_id: str
    event_type: str
    aggregate_type: str = ""
    aggregate_id: str = ""
    actor: str = "system"
    request_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryEventListResponse(BaseModel):
    events: list[MemoryEvent]
    next_after_id: int | None = None


class MemoryEventMetricsResponse(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)


class WebhookSubscriptionCreate(BaseModel):
    url: HttpUrl
    event_type: str = Field(default="*", min_length=1, max_length=120)
    confirmed: bool = False


class WebhookSubscription(BaseModel):
    subscription_id: str
    event_type: str
    url: HttpUrl
    active: bool = True
    created_at: datetime


class WebhookSubscriptionListResponse(BaseModel):
    subscriptions: list[WebhookSubscription] = Field(default_factory=list)

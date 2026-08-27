"""Typed domain-event models for the Memory Search audit/event bus."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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

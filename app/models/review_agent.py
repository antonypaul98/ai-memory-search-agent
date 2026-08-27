"""Typed contracts for the Phase 4 Review Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewQueueRequest(BaseModel):
    goal: str = Field(default="", max_length=300)
    stale_days: int = Field(default=14, ge=1, le=3650)
    limit: int = Field(default=20, ge=1, le=100)


class ReviewItem(BaseModel):
    video_id: str
    title: str
    url: str
    channel: str = ""
    goal: str
    save_reason: str = ""
    reflection_note: str = ""
    last_viewed: str | None = None
    saved_at: str
    days_since_view: int | None = None
    prompt: str


class ReviewQueueResponse(BaseModel):
    goal: str
    stale_days: int
    total_candidates: int
    items: list[ReviewItem]

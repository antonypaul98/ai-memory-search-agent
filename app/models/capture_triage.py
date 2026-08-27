"""Typed contracts for the Phase 4 Capture Triage Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.capture import CaptureUrlRequest


class CaptureTriageRequest(BaseModel):
    items: list[CaptureUrlRequest] = Field(min_length=1, max_length=100)


class CaptureTriageDecision(BaseModel):
    index: int
    original_url: str
    canonical_url: str = ""
    connector_id: str = ""
    decision: Literal["ready", "duplicate", "rejected"]
    reason: str
    duplicate_of_index: int | None = None


class CaptureTriageResponse(BaseModel):
    total: int
    ready: int
    duplicates: int
    rejected: int
    decisions: list[CaptureTriageDecision]

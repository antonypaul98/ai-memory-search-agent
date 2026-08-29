"""Typed contracts for the Phase 4 Gap Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GapAnalysisRequest(BaseModel):
    goals: list[str] = Field(default_factory=list, max_length=50)
    min_memories: int = Field(default=3, ge=1, le=100)
    min_sources: int = Field(default=2, ge=1, le=20)
    stale_days: int = Field(default=30, ge=1, le=3650)
    limit: int = Field(default=20, ge=1, le=100)


class GapFinding(BaseModel):
    kind: str
    severity: str
    message: str
    action: str
    evidence: dict[str, int | str | float | bool | None] = Field(default_factory=dict)


class GoalGapReport(BaseModel):
    goal: str
    memory_count: int
    distinct_sources: int
    stale_or_never_viewed: int
    findings: list[GapFinding]


class GoalGapNotification(BaseModel):
    """Read-only notification payload for one goal with actionable gaps."""

    goal: str
    message: str
    actions: list[str] = Field(min_length=1)


class GapAnalysisResponse(BaseModel):
    goals_analyzed: int
    goals_with_gaps: int
    reports: list[GoalGapReport]
    notifications: list[GoalGapNotification] = Field(default_factory=list)

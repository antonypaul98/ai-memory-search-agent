"""Typed contracts for Reverse Memory learning-next suggestions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReverseMemoryRequest(BaseModel):
    goals: list[str] = Field(default_factory=list, max_length=50)
    min_memories: int = Field(default=3, ge=1, le=100)
    min_sources: int = Field(default=2, ge=1, le=20)
    stale_days: int = Field(default=30, ge=1, le=3650)
    limit: int = Field(default=20, ge=1, le=100)


class LearningNextSuggestion(BaseModel):
    goal: str
    priority: int = Field(ge=1, le=4)
    kind: str
    reason: str
    action: str
    evidence: dict[str, int | str | float | bool | None] = Field(default_factory=dict)


class ReverseMemoryResponse(BaseModel):
    suggestions: list[LearningNextSuggestion]
    total: int
    goals_analyzed: int

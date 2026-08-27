"""Typed request/response models for the Phase 4c Research Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchAgentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    depth: int = Field(default=2, ge=1, le=3)
    max_sources: int = Field(default=6, ge=3, le=12)


class ResearchSource(BaseModel):
    source_id: str
    title: str
    citation_ref: str
    matched_text: str
    relevance_score: float = 0.0
    hop: int


class ResearchAgentResponse(BaseModel):
    question: str
    depth: int
    queries: list[str] = Field(default_factory=list)
    report: str
    sources: list[ResearchSource] = Field(default_factory=list)
    grounded: bool = True

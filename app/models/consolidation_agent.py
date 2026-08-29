"""Typed contracts for the Phase 4 Consolidation Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConsolidationRequest(BaseModel):
    stale_freshness_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    entity_limit: int = Field(default=500, ge=1, le=2000)
    memory_limit: int = Field(default=500, ge=1, le=2000)
    result_limit: int = Field(default=50, ge=1, le=200)


class EntityMergeSuggestion(BaseModel):
    target_entity_id: str
    target_name: str
    source_entity_id: str
    source_name: str
    entity_type: str
    reason: str


class ConsolidationMergeApproval(BaseModel):
    """Explicit human confirmation required before a proposed entity merge writes."""

    target_entity_id: str = Field(min_length=1, max_length=200)
    source_entity_id: str = Field(min_length=1, max_length=200)
    confirm: Literal[True]


class StaleMemorySuggestion(BaseModel):
    memory_id: str
    title: str
    canonical_url: str
    source_type: str
    freshness: float
    overall_trust: float
    reason: str


class ConsolidationResponse(BaseModel):
    proposed_merges: list[EntityMergeSuggestion]
    stale_memories: list[StaleMemorySuggestion]
    merge_count: int
    stale_count: int
    writes_performed: int = 0

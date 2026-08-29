"""Typed contracts for the deterministic A-02 Ingest Agent."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    connector_id: str = Field(min_length=1, max_length=80)
    match: dict[str, str] = Field(default_factory=dict)
    force_refresh: bool = False


class IngestRule(BaseModel):
    rule_id: str
    name: str
    connector_id: str
    match: dict[str, str]
    force_refresh: bool
    approved: bool
    enabled: bool


class IngestCandidate(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    attributes: dict[str, str] = Field(default_factory=dict)


class IngestAgentRunRequest(BaseModel):
    candidates: list[IngestCandidate] = Field(min_length=1, max_length=100)


class IngestAgentDecision(BaseModel):
    index: int
    decision: Literal["ingested", "duplicate", "skipped", "rejected", "failed"]
    reason: str
    canonical_url: str = ""


class IngestAgentRunResponse(BaseModel):
    rule_id: str
    total: int
    ingested: int
    duplicates: int
    skipped: int
    rejected: int
    failed: int
    decisions: list[IngestAgentDecision]
    metadata: dict[str, Any] = Field(default_factory=dict)

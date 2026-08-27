"""Schemas for provider-neutral context routing and auditable context packets."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ContextRouteStrategy(str, Enum):
    """How the router should prefer eligible context providers."""

    BALANCED = "balanced"
    FASTEST = "fastest"
    HIGHEST_TRUST = "highest_trust"
    LOWEST_COST = "lowest_cost"


class ContextRequest(BaseModel):
    """One request for the minimum trustworthy context needed for a task."""

    task: str = Field(min_length=1, max_length=4000)
    token_budget: int = Field(default=4096, ge=128, le=32768)
    max_latency_ms: int = Field(default=1500, ge=10, le=30000)
    freshness_max_age_seconds: int | None = Field(default=None, ge=0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    allowed_source_types: list[str] = Field(default_factory=list)
    strategy: ContextRouteStrategy = ContextRouteStrategy.BALANCED
    shadow: bool = Field(
        default=False,
        description=(
            "Evaluate alternate providers without allowing their evidence to change the live packet."
        ),
    )
    max_provider_calls: int = Field(default=2, ge=1, le=8)


class ContextEvidence(BaseModel):
    """Canonical evidence unit returned by any context provider."""

    evidence_id: str
    provider_id: str
    source_type: str
    source_ref: str
    title: str = ""
    text: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    observed_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    token_estimate: int = Field(default=1, ge=1)
    metadata: dict = Field(default_factory=dict)


class ContextProviderAttempt(BaseModel):
    provider_id: str
    role: str = Field(description="primary, fallback, or shadow")
    status: str = Field(description="ok, empty, skipped, deadline, or error")
    latency_ms: float = Field(default=0.0, ge=0.0)
    candidate_count: int = Field(default=0, ge=0)
    error_type: str | None = None


class ContextOmission(BaseModel):
    evidence_id: str
    provider_id: str
    reason: str


class ContextReceipt(BaseModel):
    """Auditable routing decision without raw provider credentials or hidden prompts."""

    strategy: ContextRouteStrategy
    live_provider_id: str | None = None
    provider_attempts: list[ContextProviderAttempt] = Field(default_factory=list)
    selected_evidence_ids: list[str] = Field(default_factory=list)
    omissions: list[ContextOmission] = Field(default_factory=list)
    token_budget: int
    token_estimate: int
    warnings: list[str] = Field(default_factory=list)
    route_fingerprint: str


class ContextPacket(BaseModel):
    """Prompt-ready context plus the evidence and receipt explaining how it was built."""

    task: str
    context_text: str
    evidence: list[ContextEvidence] = Field(default_factory=list)
    receipt: ContextReceipt

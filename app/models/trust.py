"""Trust scoring models persisted with universal memories."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """Verification state for a memory object."""

    UNVERIFIED = "unverified"
    PARTIAL = "partial"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class TrustTier(str, Enum):
    """Human-readable trust band derived from overall score."""

    TRUSTED = "trusted"
    MODERATE = "moderate"
    SINGLE_SOURCE = "single_source"
    LOW = "low"
    DISPUTED = "disputed"


class TrustMetrics(BaseModel):
    """Component trust scores in the range 0.0–1.0."""

    source_reliability: float = Field(ge=0.0, le=1.0)
    freshness: float = Field(ge=0.0, le=1.0)
    verification: float = Field(ge=0.0, le=1.0)
    evidence_strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)
    tier: TrustTier = TrustTier.MODERATE
    computed_at: str
    factors: dict[str, float | str | int | bool] = Field(default_factory=dict)

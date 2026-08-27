"""Claim-level verification models for grounded chat responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VerificationClaim(BaseModel):
    """Verification result for one answer claim/sentence."""

    claim: str
    status: Literal["supported", "uncertain", "unsupported"]
    evidence_ids: list[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)


class VerificationReport(BaseModel):
    """Aggregate verification report for a generated answer."""

    score: float = Field(ge=0.0, le=1.0)
    claims: list[VerificationClaim] = Field(default_factory=list)
    supported_count: int = 0
    uncertain_count: int = 0
    unsupported_count: int = 0

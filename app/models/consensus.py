"""Typed models for deterministic cross-source consensus analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConsensusSide(BaseModel):
    """One side of a detected source disagreement."""

    source_id: str
    source_title: str = ""
    claim: str


class ConsensusConflict(BaseModel):
    """Two source claims that should not be merged into one assertion."""

    reason: Literal["numeric_mismatch", "negation_mismatch"]
    similarity: float = Field(ge=0.0, le=1.0)
    side_a: ConsensusSide
    side_b: ConsensusSide


class ConsensusAgreement(BaseModel):
    """A claim independently supported by more than one source."""

    claim: str
    source_ids: list[str] = Field(default_factory=list)
    source_titles: list[str] = Field(default_factory=list)
    weight: float = Field(ge=0.0, le=1.0)


class ConsensusReport(BaseModel):
    """Deterministic summary of agreement/disagreement across retrieved sources."""

    status: Literal["insufficient_sources", "inconclusive", "agreement", "disagreement", "mixed"]
    source_count: int = Field(ge=0)
    consensus_weight: float = Field(ge=0.0, le=1.0)
    agreements: list[ConsensusAgreement] = Field(default_factory=list)
    conflicts: list[ConsensusConflict] = Field(default_factory=list)

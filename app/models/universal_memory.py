"""Universal memory object — normalized schema for all sources."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.lifecycle import LifecycleTransition, MemoryLifecycleState
from app.models.trust import TrustMetrics, VerificationStatus
from app.models.video import SourceType


class MemoryProvenance(BaseModel):
    """Origin and capture context for a memory."""

    connector_id: str = "youtube.v1"
    capture_id: str | None = None
    job_id: str | None = None
    ingest_url: str | None = None
    captured_by: str = "system"
    captured_at: str | None = None
    raw_source: dict[str, Any] = Field(default_factory=dict)


class MemoryEmbeddingRefs(BaseModel):
    """Pointers to vector indexes — embeddings stay in Chroma."""

    capsule_doc_id: str | None = None
    section_doc_ids: list[str] = Field(default_factory=list)
    evidence_doc_ids: list[str] = Field(default_factory=list)
    embedding_model: str | None = None
    chunk_count: int = 0


class MemoryVersionSnapshot(BaseModel):
    """Point-in-time version history entry."""

    version_number: int
    lifecycle_state: MemoryLifecycleState
    verification_status: VerificationStatus
    trust_overall: float | None = None
    title: str = ""
    reason: str = ""
    created_at: str
    snapshot: dict[str, Any] = Field(default_factory=dict)


class UniversalMemory(BaseModel):
    """
    Normalized memory object used by every connector and engine.

    Stored primarily in SQLite `memory_records`; vectors remain in Chroma.
    """

    memory_id: str
    user_id: str
    source_type: SourceType
    external_id: str
    canonical_url: str
    title: str
    source_author: str = ""
    lifecycle_state: MemoryLifecycleState = MemoryLifecycleState.CAPTURED
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    object_schema_version: int = 1
    content_version: int = 1
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)
    embedding_refs: MemoryEmbeddingRefs = Field(default_factory=MemoryEmbeddingRefs)
    trust: TrustMetrics | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    relationship_summary: dict[str, int] = Field(
        default_factory=dict,
        description="Counts by entity type linked in knowledge graph.",
    )
    published_at: str | None = None
    created_at: str
    updated_at: str


class UniversalMemoryDetail(UniversalMemory):
    """Memory with recent lifecycle transitions."""

    transitions: list[LifecycleTransition] = Field(default_factory=list)
    versions: list[MemoryVersionSnapshot] = Field(default_factory=list)

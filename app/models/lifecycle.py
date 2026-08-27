"""Memory lifecycle states and transition records."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MemoryLifecycleState(str, Enum):
    """Canonical lifecycle states for every universal memory object."""

    CAPTURED = "captured"
    PARSED = "parsed"
    ENRICHED = "enriched"
    EMBEDDED = "embedded"
    CONNECTED = "connected"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    MERGED = "merged"
    ARCHIVED = "archived"
    REVIVED = "revived"


# Ordered pipeline for automatic ingest progression (excluding terminal/special states).
INGEST_PIPELINE: tuple[MemoryLifecycleState, ...] = (
    MemoryLifecycleState.CAPTURED,
    MemoryLifecycleState.PARSED,
    MemoryLifecycleState.ENRICHED,
    MemoryLifecycleState.EMBEDDED,
    MemoryLifecycleState.CONNECTED,
    MemoryLifecycleState.VERIFIED,
    MemoryLifecycleState.TRUSTED,
)


class LifecycleTransition(BaseModel):
    """Audit record for a lifecycle state change."""

    memory_id: str
    from_state: MemoryLifecycleState | None = None
    to_state: MemoryLifecycleState
    reason: str = ""
    actor: str = "system"
    metadata: dict = Field(default_factory=dict)
    created_at: str


class MemoryMergeRequest(BaseModel):
    """Explicit user-confirmed duplicate merge request."""

    into_memory_id: str = Field(min_length=1, max_length=200)
    confirm: bool = False
    reason: str = Field(default="duplicate_merge", max_length=500)

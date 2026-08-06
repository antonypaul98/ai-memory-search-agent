"""Generic connector contracts — source-agnostic. YouTube lives in youtube_connector."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.video import SourceType


class TranscriptAvailability(str, Enum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"


class TranscriptKind(str, Enum):
    NONE = "none"
    MANUAL = "manual"
    AUTO_GENERATED = "auto_generated"
    UNKNOWN = "unknown"


class ProcessingStatus(str, Enum):
    QUEUED = "queued"
    METADATA = "metadata"
    TRANSCRIPT = "transcript"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"


class ConnectorHealth(BaseModel):
    connector_id: str
    healthy: bool = True
    detail: str = ""


class SourceRef(BaseModel):
    """Opaque reference to an item in a source system."""

    url: str = Field(min_length=8)
    external_id: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedItem(BaseModel):
    """Universal intermediate representation before Memory indexing."""

    source_type: SourceType
    connector_id: str
    external_id: str = Field(min_length=1)
    canonical_url: str = Field(min_length=8)
    title: str = Field(min_length=1)
    author: str = ""
    published_at: str | None = None
    duration_sec: float | None = None
    language: str | None = None
    thumbnail: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    content_hash: str = ""
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_id", "canonical_url", "title")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("must be non-empty")
        return str(v).strip()


class TextSegment(BaseModel):
    text: str
    start_time_sec: float = 0.0
    duration_sec: float = 0.0


class TranscriptPayload(BaseModel):
    external_id: str
    segments: list[TextSegment] = Field(default_factory=list)
    full_text: str = ""
    language: str | None = None
    kind: TranscriptKind = TranscriptKind.UNKNOWN
    availability: TranscriptAvailability = TranscriptAvailability.UNKNOWN


class SourceConnector(ABC):
    """
    Pluggable source connector.

    Implementations must not leak into generic ingest/search modules —
    those call only this interface.
    """

    source_type: SourceType
    connector_id: str

    @abstractmethod
    def health(self) -> ConnectorHealth:
        ...

    @abstractmethod
    def parse_ref(self, url: str) -> SourceRef:
        ...

    @abstractmethod
    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        ...

    @abstractmethod
    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        ...

    @abstractmethod
    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        ...

    def supports_url(self, url: str) -> bool:
        try:
            self.parse_ref(url)
            return True
        except Exception:
            return False

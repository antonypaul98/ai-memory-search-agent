"""YouTube Memory model — validated production schema for the YouTube connector."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.video import SourceType
from app.services.sources.base_source import (
    ProcessingStatus,
    TranscriptAvailability,
    TranscriptKind,
)


class YouTubeMemory(BaseModel):
    """Complete YouTube memory record with validation on every field."""

    memory_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    video_id: str = Field(min_length=6, max_length=32)
    url: str = Field(min_length=8)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=50000)
    channel: str = Field(default="", max_length=300)
    channel_id: str = Field(default="", max_length=128)
    published_at: str | None = None
    duration_sec: float | None = Field(default=None, ge=0)
    thumbnail: str = Field(default="", max_length=2000)
    playback_position_sec: float | None = Field(default=None, ge=0)
    language: str | None = Field(default=None, max_length=32)
    transcript_availability: TranscriptAvailability = TranscriptAvailability.UNKNOWN
    transcript_kind: TranscriptKind = TranscriptKind.UNKNOWN
    transcript_status: str = Field(default="pending", max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=100)
    categories: list[str] = Field(default_factory=list, max_length=50)
    playlist_id: str | None = Field(default=None, max_length=128)
    playlist_title: str | None = Field(default=None, max_length=500)
    playlist_index: int | None = Field(default=None, ge=0)
    saved_at: str = Field(min_length=1)
    user_notes: str = Field(default="", max_length=10000)
    embedding_status: str = Field(default="pending", max_length=64)
    processing_status: ProcessingStatus = ProcessingStatus.QUEUED
    content_hash: str = Field(default="", max_length=128)
    chunk_count: int = Field(default=0, ge=0)
    source_type: SourceType = SourceType.YOUTUBE
    connector_id: str = "youtube.v1"
    duplicate_of: str | None = None
    is_duplicate: bool = False
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(min_length=1)

    @field_validator("video_id")
    @classmethod
    def _video_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or " " in cleaned or "/" in cleaned:
            raise ValueError("invalid video_id")
        return cleaned

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not v.startswith("http"):
            raise ValueError("url must be http(s)")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> YouTubeMemory:
        if self.duration_sec is not None and self.playback_position_sec is not None:
            if self.playback_position_sec > self.duration_sec + 5:
                raise ValueError("playback_position_sec exceeds duration")
        return self


class YouTubeMemoryDetail(YouTubeMemory):
    related_count: int = 0
    pipeline_stages: list[dict[str, Any]] = Field(default_factory=list)


class RelatedMemoryItem(BaseModel):
    video_id: str
    title: str
    channel: str = ""
    url: str = ""
    relationship: str
    strength: float = Field(ge=0, le=1)
    shared_topics: list[str] = Field(default_factory=list)
    shared_entities: list[str] = Field(default_factory=list)


class RelatedMemoriesResponse(BaseModel):
    video_id: str
    items: list[RelatedMemoryItem]


class YouTubeDiagnostics(BaseModel):
    connector_id: str = "youtube.v1"
    healthy: bool = True
    videos_saved: int = 0
    transcript_success: int = 0
    transcript_failure: int = 0
    transcript_success_rate: float = 0.0
    embedding_failures: int = 0
    retry_count: int = 0
    dead_letter_count: int = 0
    average_indexing_ms: float = 0.0
    average_search_latency_ms: float = 0.0
    pending_retries: int = 0

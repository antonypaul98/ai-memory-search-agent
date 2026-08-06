"""Background job models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.reflection import ReflectionInput


class JobItemStatus(BaseModel):
    item_key: str
    url: str
    title: str = ""
    status: str
    error: str | None = None


class BackgroundJob(BaseModel):
    job_id: str
    user_id: str
    job_type: str
    playlist_id: str | None = None
    playlist_title: str = ""
    total_videos: int = 0
    queued: int = 0
    processing: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    status: str
    error_summary: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    paused: bool = False
    estimated_remaining_sec: float | None = Field(
        default=None,
        description="Rough estimate only; not a guarantee.",
    )


class JobDetailResponse(BackgroundJob):
    items: list[JobItemStatus] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)


class PlaylistIngestRequest(BaseModel):
    playlist_url: str = Field(min_length=10)
    reflection: ReflectionInput | None = None
    force_refresh: bool = False


class PlaylistPreviewResponse(BaseModel):
    playlist_id: str
    title: str
    video_count: int
    sample_titles: list[str] = Field(default_factory=list)

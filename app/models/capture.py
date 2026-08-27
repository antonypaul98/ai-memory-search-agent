"""Browser capture and bookmark models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.reflection import ReflectionInput


class ObservedContext(BaseModel):
    """Optional temporary context observed by the extension (not stored permanently by itself)."""

    platform: str = ""
    creator: str = ""
    thumbnail: str = ""
    description: str = ""
    video_id: str = ""
    duration_sec: float | None = None
    progress_sec: float | None = None
    transcript_available: bool | None = None
    tab_id: int | None = None
    window_id: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CaptureUrlRequest(BaseModel):
    url: str = Field(min_length=8)
    title: str = ""
    source_type: str = "web"
    selected_text: str = ""
    page_description: str = ""
    save_reason: str = ""
    goal: str = ""
    reflection: ReflectionInput | None = None
    browser_bookmark_folder: str = ""
    captured_at: str | None = None
    observed: ObservedContext | None = None
    async_processing: bool = True


class CaptureBatchRequest(BaseModel):
    items: list[CaptureUrlRequest] = Field(min_length=1, max_length=100)
    dedupe: bool = True


class CaptureStatusResponse(BaseModel):
    capture_id: str
    status: str
    stage: str = ""
    stage_detail: str = ""
    url: str
    title: str = ""
    job_id: str | None = None
    error: str | None = None
    message: str = ""


class BookmarkImportItem(BaseModel):
    browser_bookmark_id: str
    folder_path: str = ""
    url: str
    title: str = ""


class BookmarkImportRequest(BaseModel):
    source_browser: str = "chrome"
    sync_mode: str = "manual"  # manual | scheduled | folder | new_only
    snapshot_complete: bool = False
    items: list[BookmarkImportItem] = Field(min_length=0, max_length=500)

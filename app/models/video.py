"""Video-related schemas and source type enum."""

from enum import Enum

from pydantic import BaseModel, Field

from app.models.metrics import SearchMetrics
from app.models.reflection import ReflectionDisplay, ReflectionInput, UsageStats


class SourceType(str, Enum):
    """
    Identifies where a saved item originally came from.

    YouTube is the reference connector (V1-2). WEB, PDF, GITHUB, and BOOKMARK
    are first-class connectors (V1-4).
    """

    YOUTUBE = "youtube"
    WEB = "web"
    GITHUB = "github"
    PDF = "pdf"
    BOOKMARK = "bookmark"


class VideoMetadata(BaseModel):
    """Platform metadata fetched before ingest (backward compatible + rich fields)."""

    video_id: str = Field(description="Stable platform ID (YouTube video ID).")
    title: str = Field(description="Video title.")
    description: str = Field(default="", description="Video description.")
    channel: str = Field(description="Uploader / channel name.")
    thumbnail: str = Field(default="", description="Thumbnail image URL.")
    duration: float | None = Field(default=None, description="Duration in seconds.")
    webpage_url: str = Field(description="Canonical page URL.")
    source_type: SourceType = Field(default=SourceType.YOUTUBE)
    channel_id: str = Field(default="", description="Stable channel ID when available.")
    published_at: str | None = Field(default=None, description="ISO or YYYY-MM-DD publish date.")
    language: str | None = Field(default=None, description="Primary language code.")
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    playlist_id: str | None = None
    playlist_title: str | None = None
    playlist_index: int | None = None
    content_hash: str = ""
    connector_id: str = "youtube.v1"
    raw_metadata: dict = Field(default_factory=dict)


class IngestRequest(BaseModel):
    """Batch ingest request body."""

    urls: list[str] = Field(min_length=1, description="YouTube URLs to ingest.")
    reflection: ReflectionInput | None = Field(
        default=None,
        description="Optional save intent and recommendation preferences.",
    )
    force_refresh: bool = Field(
        default=False,
        description="Re-index videos even if already stored.",
    )


class IngestStageRecord(BaseModel):
    """One ingest pipeline stage with elapsed time."""

    stage: str
    detail: str = ""
    elapsed_ms: float = 0.0


class IngestResultItem(BaseModel):
    """Per-URL ingest outcome."""

    url: str
    success: bool
    skipped: bool = False
    video_id: str | None = None
    title: str | None = None
    channel: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    webpage_url: str | None = None
    chunk_count: int | None = None
    transcript_source: str | None = None
    error: str | None = None
    stages: list[IngestStageRecord] = Field(default_factory=list)
    elapsed_ms: float | None = None


class IngestResponse(BaseModel):
    """Batch ingest summary."""

    total: int
    succeeded: int
    failed: int
    skipped: int = 0
    elapsed_ms: float | None = None
    results: list[IngestResultItem]


class SearchResultItem(BaseModel):
    """One video-level search hit."""

    video_id: str
    title: str
    channel: str
    thumbnail: str
    url: str = Field(description="Canonical original video URL (backward compatible).")
    original_url: str = Field(description="Clickable link to the source video.")
    timestamp_url: str = Field(description="Source URL jumped to the matched timestamp.")
    duration: float | None = None
    matched_text: str
    start_time: float | None = None
    end_time: float | None = None
    relevance_score: float
    why_matched: str
    one_line_memory: str = Field(default="", description="One-sentence summary of the video.")
    why_saved: list[str] = Field(
        default_factory=list,
        description="Reasons the user may have saved this video.",
    )
    action_items: list[str] = Field(
        default_factory=list,
        description="Practical action items extracted from the transcript.",
    )
    ai_summary: str = Field(default="", description="Short AI-generated summary.")
    similarity_score: float | None = Field(
        default=None,
        description="Semantic similarity score (alias of relevance_score).",
    )
    save_reason: str = Field(default="", description="Why the user saved this memory.")
    current_goal: str = Field(default="", description="User goal when saving.")
    reflection: ReflectionDisplay = Field(default_factory=ReflectionDisplay)
    usage: UsageStats = Field(default_factory=UsageStats)
    confidence: float | None = Field(default=None, description="0–1 retrieval confidence for this hit.")
    trust_score: float | None = Field(default=None, ge=0, le=1, description="Persisted memory trust score.")
    trust_tier: str | None = Field(default=None, description="Persisted trust tier for UI badges.")
    verification_status: str | None = Field(default=None, description="Persisted memory verification status.")
    matching_metadata: list[str] = Field(default_factory=list)
    is_duplicate: bool = False
    processing_complete: bool = True
    transcript_available: bool = True
    related_video_ids: list[str] = Field(default_factory=list)
    language: str | None = None
    channel_id: str = ""
    published_at: str | None = None
    source_type: str = "youtube"
    connector_id: str = "youtube.v1"
    page_number: int | None = None
    citation_ref: str = ""
    import_date: str | None = None
    related_memories: list[str] = Field(default_factory=list)


class SearchFilters(BaseModel):
    channel: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    save_reason: str | None = Field(
        default=None,
        description="Case-insensitive substring filter over the current user's save reason.",
    )
    transcript_available: bool | None = None
    duration_min: float | None = None
    duration_max: float | None = None
    language: str | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Semantic search response."""

    query: str
    results: list[SearchResultItem]
    debug_metrics: SearchMetrics | None = None
    filters_applied: dict = Field(default_factory=dict)

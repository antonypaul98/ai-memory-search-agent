"""Transcript data models returned by the transcript fetch service."""

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """One timed segment from a YouTube transcript."""

    text: str = Field(description="Spoken text for this segment.")
    start_time_sec: float = Field(description="When this segment starts in the video.")
    duration_sec: float = Field(description="How long this segment lasts.")


class TranscriptResult(BaseModel):
    """Full transcript fetch result for one YouTube video."""

    video_id: str = Field(description="YouTube video ID extracted from the URL.")
    canonical_url: str = Field(description="Normalized YouTube watch URL.")
    segments: list[TranscriptSegment] = Field(description="Timed transcript segments.")
    full_text: str = Field(description="All segment text joined with normalized whitespace.")
    language: str | None = Field(default=None, description="Transcript language code, if known.")
    is_generated: bool = Field(
        default=False,
        description="True if captions were auto-generated rather than manually uploaded.",
    )

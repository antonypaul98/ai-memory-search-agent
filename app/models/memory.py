"""
ChromaDB metadata schema — documentation and validation model.

This model defines every field stored on each transcript CHUNK in ChromaDB.
Phase 2: model/documentation only — nothing is written to Chroma yet.

Document ID convention (Phase 3+):
    {source_type}_{item_id}_{chunk_index}
    Example: youtube_abc123_2

Each saved item (e.g. one YouTube video) produces many chunk documents.
Search hits a chunk; results are rolled up to the parent item in Phase 4.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.models.video import SourceType


class MemoryMetadata(BaseModel):
    """
    Metadata attached to every chunk document in ChromaDB.

    Required fields must be present when writing chunks (Phase 3+).
    Optional fields are omitted or set to defaults when not available.
    """

    # --- Required (all sources, Day 1) ---
    source_type: SourceType = Field(
        description="Content origin: youtube, twitter, article, etc.",
    )
    item_id: str = Field(
        description="Stable ID within the source (e.g. YouTube video ID).",
    )
    url: str = Field(
        description="Canonical URL to the original content.",
    )
    title: str = Field(
        description="Display title of the saved item.",
    )
    source_author: str = Field(
        description="Creator or publisher (YouTube channel, tweet handle, author name).",
    )
    created_at: str = Field(
        description="ISO 8601 UTC timestamp when the item was ingested into this app.",
    )
    chunk_index: int = Field(
        ge=0,
        description="Zero-based index of this chunk within the item's text.",
    )

    # --- Optional ---
    tags: list[str] = Field(
        default_factory=list,
        description="User- or system-assigned labels.",
    )
    start_time_sec: float | None = Field(
        default=None,
        description="Start timestamp of this chunk in the source media (YouTube).",
    )
    thumbnail_url: str | None = Field(
        default=None,
        description="Preview image URL (YouTube thumbnail).",
    )
    embedding_model: str | None = Field(
        default=None,
        description="Model used to embed this chunk (e.g. all-MiniLM-L6-v2). Set in Phase 3+.",
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of full normalized content for dedup/re-index detection. Phase 3+.",
    )
    published_at: str | None = Field(
        default=None,
        description="ISO 8601 UTC original publish date on the platform (not ingest time).",
    )
    platform_metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Platform-specific extras as JSON, e.g. "
            '{"duration_sec": 600, "view_count": 12000} for YouTube.'
        ),
    )

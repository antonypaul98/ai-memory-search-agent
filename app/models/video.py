"""
Video-related schemas and source type enum.

Phase 3+: VideoCreate, VideoResponse for ingest API.
"""

from enum import Enum


class SourceType(str, Enum):
    """
    Identifies where a saved item originally came from.

    V1 uses YouTube only. Future sources are listed here so metadata
    stays consistent from Day 1.
    """

    YOUTUBE = "youtube"
    # TODO: Phase 6+ — TWITTER = "twitter"
    # TODO: Phase 6+ — ARTICLE = "article"
    # TODO: Phase 6+ — INSTAGRAM = "instagram"

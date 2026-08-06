"""
Fetch display metadata from external platforms via the connector registry.

YouTube-specific fetch lives in YouTubeConnector — this service stays generic.
"""

from app.models.video import SourceType, VideoMetadata
from app.services.sources import get_connector_registry


class MetadataService:
    """Resolve URL → VideoMetadata through the appropriate SourceConnector."""

    def fetch_metadata(self, url: str) -> VideoMetadata:
        connector = get_connector_registry().resolve_for_url(url)
        ref = connector.parse_ref(url)
        item = connector.fetch_metadata(ref)
        raw = item.raw_metadata or {}
        return VideoMetadata(
            video_id=item.external_id,
            title=item.title,
            description=item.description,
            channel=item.author or str(raw.get("channel") or "Unknown"),
            channel_id=str(raw.get("channel_id") or ""),
            thumbnail=item.thumbnail,
            duration=item.duration_sec,
            webpage_url=item.canonical_url,
            source_type=item.source_type or SourceType.YOUTUBE,
            published_at=item.published_at,
            language=item.language,
            tags=list(item.tags),
            categories=list(item.categories),
            playlist_id=raw.get("playlist_id"),
            playlist_title=raw.get("playlist_title"),
            playlist_index=raw.get("playlist_index"),
            content_hash=item.content_hash,
            connector_id=item.connector_id,
            raw_metadata=dict(raw),
        )

"""Podcast RSS connector for episode show-notes/transcript ingestion."""

from __future__ import annotations

import re
from html import unescape

from app.core.exceptions import AppError
from app.models.video import SourceType
from app.services.deduplication_service import hash_text
from app.services.sources.base_source import (
    ConnectorHealth,
    NormalizedItem,
    SourceConnector,
    SourceRef,
    TextSegment,
    TranscriptAvailability,
    TranscriptKind,
    TranscriptPayload,
)

CONNECTOR_ID = "podcast.v1"
_PREFIX = "podcast://episode/"


class PodcastConnector(SourceConnector):
    """Normalize one RSS episode into the universal memory pipeline."""

    # Keep compatibility with the current universal source enum while retaining
    # podcast identity through connector_id + categories/raw_metadata.
    source_type = SourceType.WEB
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(connector_id=self.connector_id, healthy=True, detail="rss import ready")

    def parse_ref(self, url: str) -> SourceRef:
        raw = (url or "").strip()
        if not raw.startswith(_PREFIX):
            raise AppError("Podcast connector accepts only internal podcast://episode references.")
        external_id = raw[len(_PREFIX) :].strip()
        if not external_id:
            raise AppError("Podcast episode reference is missing an id.")
        return SourceRef(url=raw, external_id=external_id)

    def supports_url(self, url: str) -> bool:
        return (url or "").strip().startswith(_PREFIX)

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        title = str(ref.extra.get("title") or "Podcast episode").strip()
        show = str(ref.extra.get("show") or "").strip()
        episode_url = str(ref.extra.get("episode_url") or "").strip()
        feed_url = str(ref.extra.get("feed_url") or "").strip()
        description = _clean_html(str(ref.extra.get("description") or ""))
        transcript = _clean_html(str(ref.extra.get("transcript") or ""))
        published_at = str(ref.extra.get("published_at") or "").strip() or None
        duration = _duration_seconds(ref.extra.get("duration"))
        canonical_url = episode_url if episode_url.startswith(("http://", "https://")) else feed_url
        if not canonical_url.startswith(("http://", "https://")):
            canonical_url = f"https://podcast.local/episode/{ref.external_id}"
        material = "\n".join([title, show, canonical_url, description, transcript])
        return NormalizedItem(
            source_type=self.source_type,
            connector_id=self.connector_id,
            external_id=ref.external_id,
            canonical_url=canonical_url,
            title=title[:500],
            author=show,
            published_at=published_at,
            duration_sec=duration,
            description=description[:5000],
            categories=["podcast", "episode"],
            content_hash=hash_text(material),
            raw_metadata={
                "import_source": "podcast_rss",
                "feed_url": feed_url,
                "episode_url": episode_url,
                "guid": str(ref.extra.get("guid") or ""),
                "audio_url": str(ref.extra.get("audio_url") or ""),
                "has_transcript": bool(transcript),
                "has_show_notes": bool(description),
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        if _clean_html(str(ref.extra.get("transcript") or "")):
            return TranscriptAvailability.AVAILABLE
        if _clean_html(str(ref.extra.get("description") or "")):
            return TranscriptAvailability.PARTIAL
        return TranscriptAvailability.UNAVAILABLE

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        transcript = _clean_html(str(ref.extra.get("transcript") or ""))
        notes = _clean_html(str(ref.extra.get("description") or ""))
        text = transcript or notes
        if not text:
            return TranscriptPayload(
                external_id=ref.external_id,
                segments=[],
                full_text="",
                kind=TranscriptKind.NONE,
                availability=TranscriptAvailability.UNAVAILABLE,
            )
        parts = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z])", text) if p.strip()]
        segments = [TextSegment(text=part) for part in (parts or [text])]
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=segments,
            full_text=text,
            kind=TranscriptKind.MANUAL,
            availability=(TranscriptAvailability.AVAILABLE if transcript else TranscriptAvailability.PARTIAL),
        )


def _clean_html(value: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", value)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _duration_seconds(value) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    parts = raw.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    nums = [int(part) for part in parts]
    if len(nums) == 3:
        return float(nums[0] * 3600 + nums[1] * 60 + nums[2])
    if len(nums) == 2:
        return float(nums[0] * 60 + nums[1])
    return None

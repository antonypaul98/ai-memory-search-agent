"""Notion export connector for offline ZIP/Markdown imports."""

from __future__ import annotations

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

CONNECTOR_ID = "notion.v1"
_PREFIX = "notion://page/"


class NotionConnector(SourceConnector):
    """Normalize a Markdown page from a Notion export into memory evidence."""

    source_type = SourceType.WEB
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.connector_id,
            healthy=True,
            detail="offline export import ready",
        )

    def parse_ref(self, url: str) -> SourceRef:
        raw = (url or "").strip()
        if not raw.startswith(_PREFIX):
            raise AppError("Notion connector accepts only internal notion://page references.")
        external_id = raw[len(_PREFIX) :].strip()
        if not external_id:
            raise AppError("Notion page reference is missing an id.")
        return SourceRef(url=raw, external_id=external_id)

    def supports_url(self, url: str) -> bool:
        return (url or "").strip().startswith(_PREFIX)

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        title = str(ref.extra.get("title") or "Untitled Notion page").strip()
        markdown = str(ref.extra.get("markdown") or "").strip()
        export_path = str(ref.extra.get("export_path") or "").strip()
        content_hash = str(ref.extra.get("content_hash") or hash_text(markdown))
        return NormalizedItem(
            source_type=self.source_type,
            connector_id=self.connector_id,
            external_id=ref.external_id,
            canonical_url=f"https://notion.local/export/{ref.external_id}",
            title=title[:500],
            description="Imported from a Notion Markdown export",
            categories=["notion", "export", "markdown"],
            content_hash=content_hash,
            raw_metadata={
                "import_source": "notion_export",
                "export_path": export_path,
                "content_hash": content_hash,
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        return (
            TranscriptAvailability.AVAILABLE
            if str(ref.extra.get("markdown") or "").strip()
            else TranscriptAvailability.UNAVAILABLE
        )

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        markdown = str(ref.extra.get("markdown") or "").strip()
        segments = [TextSegment(text=markdown)] if markdown else []
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=segments,
            full_text=markdown,
            kind=TranscriptKind.MANUAL,
            availability=(
                TranscriptAvailability.AVAILABLE
                if segments
                else TranscriptAvailability.UNAVAILABLE
            ),
        )

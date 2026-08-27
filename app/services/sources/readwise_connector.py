"""Readwise highlight connector for deterministic CSV/API import payloads."""

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

CONNECTOR_ID = "readwise.v1"
_PREFIX = "readwise://article/"


class ReadwiseConnector(SourceConnector):
    """Normalize grouped Readwise highlights into one memory per source article/book."""

    # Readwise highlights ultimately point back to an article/book. Reuse WEB until
    # the universal SourceType enum gains a dedicated highlight type.
    source_type = SourceType.WEB
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(connector_id=self.connector_id, healthy=True, detail="csv import ready")

    def parse_ref(self, url: str) -> SourceRef:
        raw = (url or "").strip()
        if not raw.startswith(_PREFIX):
            raise AppError("Readwise connector accepts only internal readwise://article references.")
        external_id = raw[len(_PREFIX) :].strip()
        if not external_id:
            raise AppError("Readwise article reference is missing an id.")
        return SourceRef(url=raw, external_id=external_id)

    def supports_url(self, url: str) -> bool:
        return (url or "").strip().startswith(_PREFIX)

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        title = str(ref.extra.get("title") or "Readwise highlights").strip()
        author = str(ref.extra.get("author") or "").strip()
        source_url = str(ref.extra.get("canonical_url") or "").strip()
        if source_url.startswith(("http://", "https://")):
            # Keep the destination clickable while giving curated Readwise highlights
            # a distinct canonical identity from a separately saved full web article.
            canonical_url = f"{source_url.split('#', 1)[0]}#readwise-highlights"
        else:
            canonical_url = f"https://readwise.io/memory/{ref.external_id}"
        tags = _clean_list(ref.extra.get("tags"))
        highlights = _clean_list(ref.extra.get("highlights"))
        notes = _clean_list(ref.extra.get("notes"))
        content_material = "\n".join([title, author, source_url, *highlights, *notes])
        return NormalizedItem(
            source_type=self.source_type,
            connector_id=self.connector_id,
            external_id=ref.external_id,
            canonical_url=canonical_url,
            title=title[:500],
            author=author,
            description=f"Imported from Readwise · {len(highlights)} highlight(s)",
            tags=tags,
            categories=["readwise", "highlight"],
            content_hash=hash_text(content_material),
            raw_metadata={
                "import_source": "readwise",
                "source_url": source_url,
                "highlight_count": len(highlights),
                "tags": tags,
                "locations": _clean_list(ref.extra.get("locations")),
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        return TranscriptAvailability.AVAILABLE if _clean_list(ref.extra.get("highlights")) else TranscriptAvailability.UNAVAILABLE

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        highlights = _clean_list(ref.extra.get("highlights"))
        notes = _clean_list(ref.extra.get("notes"))
        segments: list[TextSegment] = []
        for idx, highlight in enumerate(highlights):
            note = notes[idx] if idx < len(notes) else ""
            text = highlight if not note else f"{highlight}\nNote: {note}"
            segments.append(TextSegment(text=text))
        full_text = "\n\n".join(segment.text for segment in segments)
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=segments,
            full_text=full_text,
            kind=TranscriptKind.MANUAL,
            availability=(TranscriptAvailability.AVAILABLE if segments else TranscriptAvailability.UNAVAILABLE),
        )


def _clean_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        items = list(value)
    return [str(item).strip() for item in items if str(item).strip()]

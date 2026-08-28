"""Google Drive connector for OAuth-backed Docs/PDF ingestion."""

from __future__ import annotations

import re

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

CONNECTOR_ID = "gdrive.v1"
_PREFIX = "gdrive://file/"
_GOOGLE_DOC = "application/vnd.google-apps.document"
_PDF = "application/pdf"


class GoogleDriveConnector(SourceConnector):
    """Normalize an already-authorized Drive file into Universal Memory."""

    source_type = SourceType.WEB
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.connector_id,
            healthy=True,
            detail="OAuth-backed Google Docs/PDF import ready",
        )

    def parse_ref(self, url: str) -> SourceRef:
        raw = (url or "").strip()
        if not raw.startswith(_PREFIX):
            raise AppError("Google Drive connector accepts only internal gdrive://file references.")
        external_id = raw[len(_PREFIX) :].strip()
        if not external_id or "/" in external_id:
            raise AppError("Google Drive file reference is missing a valid id.")
        return SourceRef(url=raw, external_id=external_id)

    def supports_url(self, url: str) -> bool:
        return (url or "").strip().startswith(_PREFIX)

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        mime_type = str(ref.extra.get("mime_type") or "").strip()
        if mime_type not in {_GOOGLE_DOC, _PDF}:
            raise AppError("Google Drive connector supports Google Docs and PDFs only.")
        title = str(ref.extra.get("name") or "Google Drive file").strip()
        text = str(ref.extra.get("text") or "").strip()
        if not text:
            raise AppError("Google Drive file has no extractable text.")
        web_url = str(ref.extra.get("web_view_link") or "").strip()
        canonical_url = web_url if web_url.startswith("https://") else f"https://drive.google.com/open?id={ref.external_id}"
        material = "\n".join([ref.external_id, title, mime_type, text])
        return NormalizedItem(
            source_type=SourceType.PDF if mime_type == _PDF else SourceType.WEB,
            connector_id=self.connector_id,
            external_id=ref.external_id,
            canonical_url=canonical_url,
            title=title[:500],
            published_at=str(ref.extra.get("modified_time") or "").strip() or None,
            description=("Google Drive PDF" if mime_type == _PDF else "Google Doc"),
            categories=["google-drive", "pdf" if mime_type == _PDF else "document"],
            content_hash=str(ref.extra.get("content_hash") or "").strip() or hash_text(material),
            raw_metadata={
                "import_source": "google_drive",
                "drive_file_id": ref.external_id,
                "mime_type": mime_type,
                "modified_time": str(ref.extra.get("modified_time") or ""),
                "web_view_link": web_url,
                "provider_checksum": str(ref.extra.get("provider_checksum") or ""),
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        return TranscriptAvailability.AVAILABLE if str(ref.extra.get("text") or "").strip() else TranscriptAvailability.UNAVAILABLE

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        text = str(ref.extra.get("text") or "").strip()
        if not text:
            return TranscriptPayload(
                external_id=ref.external_id,
                segments=[],
                full_text="",
                kind=TranscriptKind.NONE,
                availability=TranscriptAvailability.UNAVAILABLE,
            )
        parts = [part.strip() for part in re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z])", text) if part.strip()]
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=[TextSegment(text=part) for part in (parts or [text])],
            full_text=text,
            kind=TranscriptKind.MANUAL,
            availability=TranscriptAvailability.AVAILABLE,
        )

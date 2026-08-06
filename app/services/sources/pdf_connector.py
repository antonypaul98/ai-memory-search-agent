"""PDF document connector — local/upload bytes via pypdf."""

from __future__ import annotations

import io
from pathlib import Path

from app.core.exceptions import AppError, MetadataFetchError, TranscriptUnavailableError
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

CONNECTOR_ID = "pdf.v1"
_MAX_PAGES_DEFAULT = 500
_MAX_BYTES_DEFAULT = 50 * 1024 * 1024


class PDFConnector(SourceConnector):
    source_type = SourceType.PDF
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        try:
            import pypdf  # noqa: F401

            return ConnectorHealth(connector_id=self.connector_id, healthy=True, detail="ok")
        except Exception as exc:
            return ConnectorHealth(connector_id=self.connector_id, healthy=False, detail=str(exc))

    def parse_ref(self, url: str) -> SourceRef:
        raw = url.strip()
        if raw.startswith("pdf://"):
            external_id = raw[6:] or hash_text(raw)[:24]
            return SourceRef(url=raw, external_id=external_id)
        if raw.lower().endswith(".pdf") or raw.startswith("file:"):
            path = raw.replace("file://", "")
            external_id = hash_text(path)[:24]
            return SourceRef(url=raw, external_id=external_id, extra={"path": path})
        # http(s) PDF URL
        if raw.startswith("http") and ".pdf" in raw.lower():
            from app.services.ssrf_fetch import validate_public_http_url

            safe = validate_public_http_url(raw, resolve_dns=False)
            return SourceRef(url=safe, external_id=hash_text(safe)[:24], extra={"remote": True})
        raise AppError("Not a PDF reference.")

    def supports_url(self, url: str) -> bool:
        try:
            self.parse_ref(url)
            return True
        except Exception:
            return False

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        if ref.extra.get("pages_text"):
            pages = list(ref.extra["pages_text"])
            title = str(ref.extra.get("filename") or ref.extra.get("title") or f"PDF {ref.external_id}")
            sample = "\n".join(pages[:3])
            return NormalizedItem(
                source_type=self.source_type,
                connector_id=self.connector_id,
                external_id=ref.external_id or hash_text(ref.url)[:24],
                canonical_url=ref.url if ref.url.startswith("http") else f"pdf://{ref.external_id}",
                title=title[:500],
                author=str(ref.extra.get("author") or ""),
                description=sample[:2000],
                content_hash=hash_text(sample or title),
                raw_metadata={
                    "page_count": len(pages),
                    "scanned_or_empty_text": len(sample.strip()) < 20,
                    "encrypted": False,
                    "filename": ref.extra.get("filename") or "",
                },
            )
        reader, meta = self._open(ref)
        title = (
            (meta.get("/Title") if meta else None)
            or ref.extra.get("filename")
            or ref.extra.get("title")
            or f"PDF {ref.external_id}"
        )
        author = str(meta.get("/Author") or "") if meta else ""
        pages = len(reader.pages)
        text_sample = ""
        for i, page in enumerate(reader.pages[:3]):
            try:
                text_sample += (page.extract_text() or "") + "\n"
            except Exception:
                continue
        scanned = pages > 0 and len(text_sample.strip()) < 20
        content_hash = hash_text(text_sample or title)
        return NormalizedItem(
            source_type=self.source_type,
            connector_id=self.connector_id,
            external_id=ref.external_id or hash_text(ref.url)[:24],
            canonical_url=ref.url if ref.url.startswith("http") else f"pdf://{ref.external_id}",
            title=str(title)[:500],
            author=author[:300],
            description=text_sample[:2000],
            content_hash=content_hash,
            raw_metadata={
                "page_count": pages,
                "scanned_or_empty_text": scanned,
                "encrypted": bool(getattr(reader, "is_encrypted", False)),
                "filename": ref.extra.get("filename") or "",
                "pdf_metadata": {str(k): str(v)[:200] for k, v in (meta or {}).items()},
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        try:
            item = self.fetch_metadata(ref)
            if item.raw_metadata.get("encrypted"):
                return TranscriptAvailability.DISABLED
            if item.raw_metadata.get("scanned_or_empty_text"):
                return TranscriptAvailability.UNAVAILABLE
            return TranscriptAvailability.AVAILABLE
        except Exception:
            return TranscriptAvailability.UNKNOWN

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        if ref.extra.get("pages_text"):
            pages = [str(p).strip() for p in ref.extra["pages_text"] if str(p).strip()]
            if not pages:
                raise TranscriptUnavailableError(
                    "No extractable text (scanned PDF or OCR unavailable)."
                )
            segments = [
                TextSegment(text=text, start_time_sec=float(idx + 1), duration_sec=0.0)
                for idx, text in enumerate(pages)
            ]
            return TranscriptPayload(
                external_id=ref.external_id,
                segments=segments,
                full_text="\n\n".join(pages),
                kind=TranscriptKind.MANUAL,
                availability=TranscriptAvailability.AVAILABLE,
            )
        reader, _meta = self._open(ref)
        if getattr(reader, "is_encrypted", False):
            raise TranscriptUnavailableError("PDF is encrypted; cannot extract text.")
        segments: list[TextSegment] = []
        parts: list[str] = []
        max_pages = int(ref.extra.get("max_pages") or _MAX_PAGES_DEFAULT)
        for idx, page in enumerate(reader.pages[:max_pages]):
            try:
                text = (page.extract_text() or "").strip()
            except Exception as exc:
                raise MetadataFetchError(f"Failed extracting page {idx + 1}: {exc}") from exc
            if not text:
                continue
            # Page number stored as start_time_sec for citation (page N).
            segments.append(
                TextSegment(text=text, start_time_sec=float(idx + 1), duration_sec=0.0)
            )
            parts.append(text)
        if not segments:
            raise TranscriptUnavailableError(
                "No extractable text (scanned PDF or OCR unavailable)."
            )
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=segments,
            full_text="\n\n".join(parts),
            kind=TranscriptKind.MANUAL,
            availability=TranscriptAvailability.AVAILABLE,
        )

    def _open(self, ref: SourceRef):
        from pypdf import PdfReader

        data = ref.extra.get("bytes")
        if data is None and ref.extra.get("path"):
            path = Path(str(ref.extra["path"]))
            if not path.is_file():
                raise MetadataFetchError(f"PDF file not found: {path}")
            size = path.stat().st_size
            if size > _MAX_BYTES_DEFAULT:
                raise MetadataFetchError("PDF too large.")
            data = path.read_bytes()
        if data is None and ref.extra.get("remote"):
            data = _download_pdf(ref.url)
        if data is None:
            raise MetadataFetchError("PDF bytes not provided.")
        if len(data) > _MAX_BYTES_DEFAULT:
            raise MetadataFetchError("PDF too large.")
        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as exc:
            raise MetadataFetchError(f"Failed to open PDF: {exc}") from exc
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception as exc:
                raise TranscriptUnavailableError(f"Encrypted PDF: {exc}") from exc
        return reader, reader.metadata


def _download_pdf(url: str) -> bytes:
    import httpx

    from app.config import get_settings
    from app.services.ssrf_fetch import validate_public_http_url

    settings = get_settings()
    safe = validate_public_http_url(url)
    with httpx.Client(timeout=settings.capture_fetch_timeout_sec, follow_redirects=True) as client:
        resp = client.get(safe)
        resp.raise_for_status()
        if len(resp.content) > _MAX_BYTES_DEFAULT:
            raise MetadataFetchError("PDF too large.")
        return resp.content

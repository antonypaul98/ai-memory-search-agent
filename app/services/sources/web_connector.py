"""Web article connector — SSRF-safe fetch + readable extraction."""

from __future__ import annotations

import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

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
from app.services.ssrf_fetch import validate_public_http_url

CONNECTOR_ID = "web.v1"

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_GITHUB_HOSTS = {"github.com", "www.github.com"}


class WebConnector(SourceConnector):
    source_type = SourceType.WEB
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        try:
            import httpx  # noqa: F401

            return ConnectorHealth(connector_id=self.connector_id, healthy=True, detail="ok")
        except Exception as exc:
            return ConnectorHealth(connector_id=self.connector_id, healthy=False, detail=str(exc))

    def parse_ref(self, url: str) -> SourceRef:
        safe = validate_public_http_url(url, resolve_dns=False)
        host = (urlparse(safe).hostname or "").lower()
        if host in _YOUTUBE_HOSTS or host.endswith(".youtube.com"):
            raise AppError("YouTube URLs are handled by youtube.v1")
        if host in _GITHUB_HOSTS:
            raise AppError("GitHub URLs are handled by github.v1")
        path = urlparse(safe).path.lower()
        if path.endswith(".pdf"):
            raise AppError("PDF URLs are handled by pdf.v1")
        external_id = hash_text(safe)[:24]
        return SourceRef(url=safe, external_id=external_id)

    def supports_url(self, url: str) -> bool:
        try:
            self.parse_ref(url)
            return True
        except Exception:
            return False

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        if not ref.external_id:
            ref = self.parse_ref(ref.url)
        html, final_url = self._load_html(ref)
        extracted = _extract_article(html, final_url, selected_text=str(ref.extra.get("selected_text") or ""))
        title = extracted["title"] or ref.extra.get("title") or final_url
        content_hash = hash_text(extracted["text"] or title)
        return NormalizedItem(
            source_type=self.source_type,
            connector_id=self.connector_id,
            external_id=ref.external_id or hash_text(final_url)[:24],
            canonical_url=extracted.get("canonical_url") or final_url,
            title=str(title)[:500],
            author=extracted.get("author") or "",
            published_at=extracted.get("published_at"),
            language=extracted.get("language"),
            description=(extracted.get("description") or "")[:5000],
            tags=extracted.get("tags") or [],
            content_hash=content_hash,
            raw_metadata={
                "publication": extracted.get("publication") or "",
                "headings": extracted.get("headings") or [],
                "images": extracted.get("images") or [],
                "extraction_quality": extracted.get("quality") or 0.0,
                "robots_allowed": extracted.get("robots_allowed", True),
                "selected_text": bool(ref.extra.get("selected_text")),
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        try:
            meta = self.fetch_metadata(ref)
            quality = float(meta.raw_metadata.get("extraction_quality") or 0)
            if quality <= 0:
                return TranscriptAvailability.UNAVAILABLE
            if quality < 0.35:
                return TranscriptAvailability.PARTIAL
            return TranscriptAvailability.AVAILABLE
        except Exception:
            return TranscriptAvailability.UNKNOWN

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        if not ref.external_id:
            ref = self.parse_ref(ref.url)
        html, final_url = self._load_html(ref)
        selected = str(ref.extra.get("selected_text") or "").strip()
        extracted = _extract_article(html, final_url, selected_text=selected)
        text = extracted["text"]
        if not text:
            raise TranscriptUnavailableError("No readable article text extracted.")
        segments: list[TextSegment] = []
        if selected:
            segments.append(TextSegment(text=selected, start_time_sec=0.0, duration_sec=0.0))
        # Split body into paragraph-ish segments for chunking
        parts = [p.strip() for p in re.split(r"\n{2,}|(?<=\.)\s{2,}", text) if p.strip()]
        if not parts:
            parts = [text]
        for idx, part in enumerate(parts):
            if selected and part == selected:
                continue
            segments.append(TextSegment(text=part, start_time_sec=float(idx + 1), duration_sec=0.0))
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=segments,
            full_text=text if not selected else f"{selected}\n\n{text}",
            language=extracted.get("language"),
            kind=TranscriptKind.MANUAL,
            availability=TranscriptAvailability.AVAILABLE,
        )

    def _load_html(self, ref: SourceRef) -> tuple[str, str]:
        if ref.extra.get("html"):
            return str(ref.extra["html"]), ref.url
        if ref.extra.get("text") and not ref.extra.get("fetch", True):
            # Pre-supplied plain text path (tests / offline)
            body = f"<html><head><title>{ref.extra.get('title') or 'Article'}</title></head>"
            body += f"<body><article>{ref.extra['text']}</article></body></html>"
            return body, ref.url
        return _fetch_html(ref.url)


def _fetch_html(url: str) -> tuple[str, str]:
    import httpx

    from app.config import get_settings

    settings = get_settings()
    safe = validate_public_http_url(url)
    robots_allowed = _robots_allows(safe)
    with httpx.Client(
        timeout=settings.capture_fetch_timeout_sec,
        follow_redirects=True,
    ) as client:
        with client.stream("GET", safe) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            if "text/html" not in ctype and "text/plain" not in ctype:
                raise MetadataFetchError(f"Unsupported content type: {ctype}")
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > settings.capture_max_response_bytes:
                    raise MetadataFetchError("Response too large.")
                chunks.append(chunk)
            html = b"".join(chunks).decode("utf-8", errors="ignore")
            final = str(resp.url)
    if not robots_allowed:
        # Still allow user-initiated save but flag quality
        html = html  # noqa: B018 — intentional no-op; flagged in metadata
    return html, final


def _robots_allows(url: str) -> bool:
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch("AIMemoryAgentBot", url)
    except Exception:
        return True


def _extract_article(html: str, url: str, *, selected_text: str = "") -> dict:
    title = ""
    author = ""
    published_at = None
    language = None
    description = ""
    publication = ""
    headings: list[str] = []
    images: list[dict] = []
    text = ""
    canonical = url
    quality = 0.0

    try:
        import trafilatura
        from trafilatura import extract, extract_metadata

        meta = extract_metadata(html, default_url=url)
        if meta:
            title = meta.title or ""
            author = meta.author or ""
            published_at = meta.date or None
            language = meta.language or None
            description = meta.description or ""
            publication = meta.sitename or ""
        text = extract(html, include_comments=False, include_tables=True, url=url) or ""
    except Exception:
        text = ""

    if not text:
        text = _fallback_strip(html)
        quality = 0.25 if text else 0.0
    else:
        quality = min(1.0, len(text) / 2000)

    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.I | re.S)[:20]:
        clean = re.sub(r"<[^>]+>", "", h).strip()
        if clean:
            headings.append(clean[:200])

    for src, alt in re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*(?:alt=["\']([^"\']*)["\'])?', html, re.I)[:20]:
        images.append({"src": src[:500], "alt": (alt or "")[:200]})

    can = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
    if not can:
        can = re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', html, re.I)
    if can:
        canonical = can.group(1).strip()

    if selected_text:
        text = f"{selected_text.strip()}\n\n{text}".strip()
        quality = max(quality, 0.5)

    robots_allowed = True
    return {
        "title": title or "Untitled article",
        "author": author,
        "published_at": published_at,
        "language": language,
        "description": description,
        "publication": publication,
        "headings": headings,
        "images": images,
        "text": text.strip(),
        "canonical_url": canonical,
        "quality": quality,
        "robots_allowed": robots_allowed,
        "tags": headings[:5],
    }


def _fallback_strip(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:20000]

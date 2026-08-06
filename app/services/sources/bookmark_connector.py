"""Chrome bookmark connector — folder import preview + URL delegation."""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.exceptions import AppError
from app.models.video import SourceType
from app.services.deduplication_service import hash_text
from app.services.sources.base_source import (
    ConnectorHealth,
    NormalizedItem,
    SourceConnector,
    SourceRef,
    TranscriptAvailability,
    TranscriptKind,
    TranscriptPayload,
    TextSegment,
)

CONNECTOR_ID = "bookmarks.v1"


class BookmarkConnector(SourceConnector):
    """
    Bookmark connector does not fetch page bodies itself.

    It normalizes bookmark folder metadata and lets ImportManager resolve
    each bookmark URL to youtube/web/github/pdf connectors.
    """

    source_type = SourceType.BOOKMARK
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(connector_id=self.connector_id, healthy=True, detail="ok")

    def parse_ref(self, url: str) -> SourceRef:
        # Bookmark connector is not a URL resolver for arbitrary pages.
        if url.startswith("bookmark://"):
            external_id = url.split("bookmark://", 1)[-1] or hash_text(url)[:16]
            return SourceRef(url=url, external_id=external_id)
        raise AppError("Bookmark connector does not resolve arbitrary URLs.")

    def supports_url(self, url: str) -> bool:
        return url.strip().startswith("bookmark://")

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        title = str(ref.extra.get("title") or "Bookmark")
        folder = str(ref.extra.get("folder_path") or "")
        tags = list(ref.extra.get("tags") or [])
        target = str(ref.extra.get("target_url") or ref.url)
        return NormalizedItem(
            source_type=self.source_type,
            connector_id=self.connector_id,
            external_id=ref.external_id or hash_text(target)[:24],
            canonical_url=target if target.startswith("http") else ref.url,
            title=title[:500],
            description=folder,
            tags=tags,
            categories=[folder] if folder else [],
            content_hash=hash_text(target),
            raw_metadata={
                "folder_path": folder,
                "browser_bookmark_id": ref.extra.get("browser_bookmark_id") or "",
                "source_browser": ref.extra.get("source_browser") or "chrome",
                "target_url": target,
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        return TranscriptAvailability.UNAVAILABLE

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        # Bookmarks are catalog entries; body comes from target connector.
        note = str(ref.extra.get("title") or "Bookmark")
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=[TextSegment(text=note)],
            full_text=note,
            kind=TranscriptKind.NONE,
            availability=TranscriptAvailability.UNAVAILABLE,
        )

    def preview_import(self, items: list[dict], *, known_url_hashes: set[str] | None = None) -> dict:
        """Return bookmark count / duplicate / unsupported preview stats."""
        known = known_url_hashes or set()
        seen: set[str] = set()
        supported = 0
        duplicates = 0
        unsupported = 0
        folders: set[str] = set()
        for item in items:
            url = str(item.get("url") or "").strip()
            folder = str(item.get("folder_path") or "")
            if folder:
                folders.add(folder)
            if not url.startswith("http"):
                unsupported += 1
                continue
            host = (urlparse(url).hostname or "").lower()
            if not host:
                unsupported += 1
                continue
            h = hash_text(url)
            if h in seen or h in known:
                duplicates += 1
                continue
            seen.add(h)
            supported += 1
        return {
            "bookmark_count": len(items),
            "importable_count": supported,
            "duplicate_count": duplicates,
            "unsupported_count": unsupported,
            "folder_count": len(folders),
            "folders": sorted(folders)[:50],
        }

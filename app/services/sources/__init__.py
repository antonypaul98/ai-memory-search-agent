"""Connector registry — maps connector_id / URL to SourceConnector instances."""

from __future__ import annotations

from functools import lru_cache

from app.core.exceptions import AppError
from app.services.sources.base_source import SourceConnector
from app.services.sources.bookmark_connector import BookmarkConnector
from app.services.sources.gdrive_connector import GoogleDriveConnector
from app.services.sources.github_connector import GitHubConnector
from app.services.sources.notion_connector import NotionConnector
from app.services.sources.pdf_connector import PDFConnector
from app.services.sources.podcast_connector import PodcastConnector
from app.services.sources.readwise_connector import ReadwiseConnector
from app.services.sources.web_connector import WebConnector
from app.services.sources.youtube_connector import CONNECTOR_ID as YOUTUBE_ID
from app.services.sources.youtube_connector import YouTubeConnector

# Specific → general resolution order (first match wins).
_RESOLVE_ORDER = (
    "youtube.v1",
    "github.v1",
    "pdf.v1",
    "gdrive.v1",
    "podcast.v1",
    "web.v1",
    "bookmarks.v1",
    "readwise.v1",
    "notion.v1",
)


class ConnectorRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, SourceConnector] = {}
        self.register(YouTubeConnector())
        self.register(GitHubConnector())
        self.register(PDFConnector())
        self.register(GoogleDriveConnector())
        self.register(PodcastConnector())
        self.register(WebConnector())
        self.register(BookmarkConnector())
        self.register(ReadwiseConnector())
        self.register(NotionConnector())

    def register(self, connector: SourceConnector) -> None:
        self._by_id[connector.connector_id] = connector

    def get(self, connector_id: str) -> SourceConnector:
        conn = self._by_id.get(connector_id)
        if not conn:
            raise AppError(f"Unknown connector: {connector_id}")
        return conn

    def resolve_for_url(self, url: str) -> SourceConnector:
        for connector_id in _RESOLVE_ORDER:
            connector = self._by_id.get(connector_id)
            if connector and connector.supports_url(url):
                return connector
        for connector in self._by_id.values():
            if connector.supports_url(url):
                return connector
        raise AppError("No connector supports this URL.")

    def list_connectors(self) -> list[str]:
        return sorted(self._by_id.keys())

    def health_all(self) -> list[dict]:
        return [
            self.get(cid).health().model_dump()
            for cid in self.list_connectors()
        ]


@lru_cache
def get_connector_registry() -> ConnectorRegistry:
    return ConnectorRegistry()


def reset_connector_registry_cache() -> None:
    get_connector_registry.cache_clear()


def get_youtube_connector() -> YouTubeConnector:
    return get_connector_registry().get(YOUTUBE_ID)  # type: ignore[return-value]

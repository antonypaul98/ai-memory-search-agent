from __future__ import annotations

import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.services.podcast_import_service import PodcastImportService
from app.services.sources import ConnectorRegistry
from app.services.sources.base_source import TranscriptAvailability


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Memory Lab</title>
    <item>
      <guid>episode-1</guid>
      <title>Grounded Retrieval</title>
      <link>https://example.com/episodes/1</link>
      <pubDate>Thu, 27 Aug 2026 12:00:00 GMT</pubDate>
      <content:encoded><![CDATA[<p>Evidence first.</p><p>Always preserve citations.</p>]]></content:encoded>
      <itunes:duration>01:02:03</itunes:duration>
      <enclosure url="https://cdn.example.com/1.mp3" type="audio/mpeg" />
    </item>
    <item>
      <guid>episode-1</guid>
      <title>Duplicate copy</title>
      <description>Should deduplicate by GUID.</description>
    </item>
  </channel>
</rss>
"""


def test_podcast_preview_is_deterministic_and_deduplicates_guid():
    service = PodcastImportService(Settings())
    preview = service.preview("https://example.com/feed.xml", xml_text=RSS)

    assert preview["show"] == "Memory Lab"
    assert preview["total_discovered"] == 1
    episode = preview["episodes"][0]
    assert episode["title"] == "Grounded Retrieval"
    assert episode["episode_url"] == "https://example.com/episodes/1"
    assert episode["description"] == "<p>Evidence first.</p><p>Always preserve citations.</p>"
    assert len(episode["external_id"]) == 24


def test_podcast_connector_preserves_provenance_and_indexes_show_notes():
    service = PodcastImportService(Settings())
    episode = service.preview("https://example.com/feed.xml", xml_text=RSS)["episodes"][0]
    connector = ConnectorRegistry().get("podcast.v1")
    ref = connector.parse_ref(f"podcast://episode/{episode['external_id']}")
    ref.extra.update(episode)
    ref.extra["feed_url"] = "https://example.com/feed.xml"

    metadata = connector.fetch_metadata(ref)
    transcript = connector.fetch_transcript(ref)

    assert metadata.connector_id == "podcast.v1"
    assert metadata.categories == ["podcast", "episode"]
    assert metadata.raw_metadata["feed_url"] == "https://example.com/feed.xml"
    assert metadata.raw_metadata["guid"] == "episode-1"
    assert metadata.duration_sec == 3723.0
    assert transcript.availability == TranscriptAvailability.PARTIAL
    assert "Evidence first" in transcript.full_text
    assert "Always preserve citations" in transcript.full_text


def test_podcast_preview_rejects_private_feed_even_with_fixture_xml():
    service = PodcastImportService(Settings())
    with pytest.raises(AppError, match="Blocked host|Private network"):
        service.preview("http://localhost/feed.xml", xml_text=RSS)


def test_podcast_preview_rejects_dtd_and_entity_payloads():
    service = PodcastImportService(Settings())
    xml = "<!DOCTYPE rss [<!ENTITY x 'boom'>]><rss><channel><title>x</title><item><title>&x;</title></item></channel></rss>"
    with pytest.raises(AppError, match="unsupported XML declarations"):
        service.preview("https://example.com/feed.xml", xml_text=xml)


def test_registry_exposes_podcast_connector():
    registry = ConnectorRegistry()
    assert "podcast.v1" in registry.list_connectors()
    assert registry.resolve_for_url("podcast://episode/abc123").connector_id == "podcast.v1"

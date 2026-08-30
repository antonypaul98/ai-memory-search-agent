from __future__ import annotations

from types import SimpleNamespace

from app.config import Settings
from app.services import podcast_import_service as podcast_module
from app.services.podcast_import_service import PodcastImportService


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Memory Lab</title>
    <item>
      <guid>episode-acceptance-1</guid>
      <title>Evidence First</title>
      <link>https://example.com/episodes/evidence-first</link>
      <description><![CDATA[<p>Preserve source evidence and provenance.</p>]]></description>
    </item>
  </channel>
</rss>
"""


def test_podcast_ingest_forwards_tenant_canonical_ref_and_feed_provenance(monkeypatch):
    calls: list[dict] = []

    class FakeConnectorIngestService:
        def __init__(self, settings):
            self.settings = settings

        def ingest_url(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return SimpleNamespace(
                video_id=kwargs["ref_extra"]["external_id"],
                title=kwargs["ref_extra"]["title"],
                success=True,
                skipped=False,
                chunk_count=1,
                error=None,
            )

    monkeypatch.setattr(podcast_module, "ConnectorIngestService", FakeConnectorIngestService)
    service = PodcastImportService(Settings())

    first = service.ingest(
        "https://example.com/feed.xml",
        user_id="tenant-a",
        xml_text=RSS,
    )
    second = service.ingest(
        "https://example.com/feed.xml",
        user_id="tenant-b",
        xml_text=RSS,
    )

    assert first["succeeded"] == 1
    assert second["succeeded"] == 1
    assert len(calls) == 2
    assert calls[0]["url"] == calls[1]["url"]
    assert calls[0]["url"].startswith("podcast://episode/")
    assert calls[0]["user_id"] == "tenant-a"
    assert calls[1]["user_id"] == "tenant-b"
    assert calls[0]["connector_id"] == calls[1]["connector_id"] == "podcast.v1"
    assert calls[0]["ref_extra"]["feed_url"] == "https://example.com/feed.xml"
    assert calls[0]["ref_extra"]["description"] == "<p>Preserve source evidence and provenance.</p>"

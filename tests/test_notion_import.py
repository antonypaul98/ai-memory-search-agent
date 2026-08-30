from __future__ import annotations

import io
import zipfile

import pytest

from app.config import Settings
from app.models.video import IngestResultItem
from app.services.notion_import_service import NotionImportService
from app.services.sources import ConnectorRegistry
from app.services.sources.notion_connector import NotionConnector


class FakeIngest:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_url(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return IngestResultItem(
            url=url,
            success=True,
            skipped=False,
            video_id=url.rsplit("/", 1)[-1],
            title=kwargs["ref_extra"]["title"],
            chunk_count=1,
        )


def _zip(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def _service(tmp_path, fake=None):
    settings = Settings(
        sqlite_path=str(tmp_path / "db.sqlite"),
        chroma_persist_dir=str(tmp_path / "chroma"),
    )
    return NotionImportService(settings, ingest_service=fake or FakeIngest())


def test_notion_zip_parses_nested_markdown_and_preserves_provenance(tmp_path):
    service = _service(tmp_path)
    data = _zip(
        {
            "Projects/Memory Agent abcdefabcdefabcdefabcdefabcdefab.md": "# Memory Agent\n\nCanonical records and evidence.",
            "Notes/Plain page.md": "A page without an H1.",
            "assets/image.png": "not markdown",
        }
    )

    preview = service.preview_zip(data)

    assert preview["page_count"] == 2
    pages = {page["title"]: page for page in preview["pages"]}
    assert "Memory Agent" in pages
    assert "Plain page" in pages
    assert pages["Memory Agent"]["export_path"].startswith("Projects/")
    assert len(pages["Memory Agent"]["content_hash"]) == 64


def test_notion_import_is_tenant_scoped_and_uses_registered_connector(tmp_path):
    fake = FakeIngest()
    service = _service(tmp_path, fake)
    data = _zip({"Page.md": "# Page\n\nUseful content."})

    result = service.ingest_zip(data, user_id="tenant-a", force_refresh=True)

    assert result["page_count"] == 1
    assert result["succeeded"] == 1
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["user_id"] == "tenant-a"
    assert call["force_refresh"] is True
    assert call["connector_id"] == "notion.v1"
    assert call["url"].startswith("notion://page/")
    assert call["ref_extra"]["export_path"] == "Page.md"
    assert "Notion export" in call["reflection"].reflection_note


def test_notion_connector_preserves_markdown_as_groundable_evidence():
    connector = NotionConnector()
    ref = connector.parse_ref("notion://page/abc123")
    ref.extra.update(
        {
            "title": "Architecture",
            "markdown": "# Architecture\n\nUse canonical records.\n\n## Evidence\nKeep provenance.",
            "export_path": "Docs/Architecture.md",
            "content_hash": "abc",
        }
    )

    item = connector.fetch_metadata(ref)
    transcript = connector.fetch_transcript(ref)

    assert item.connector_id == "notion.v1"
    assert item.raw_metadata["export_path"] == "Docs/Architecture.md"
    assert item.raw_metadata["content_hash"] == "abc"
    assert transcript.full_text.startswith("# Architecture")
    assert len(transcript.segments) == 1
    assert "Keep provenance" in transcript.segments[0].text


def test_notion_export_deduplicates_identical_pages_deterministically(tmp_path):
    service = _service(tmp_path)
    data = _zip({"A.md": "# Same\nBody", "Nested/B.md": "# Same\nBody"})

    first = service.preview_zip(data)
    second = service.preview_zip(data)

    assert first == second
    assert first["page_count"] == 1


def test_notion_export_rejects_zip_slip_paths(tmp_path):
    service = _service(tmp_path)
    data = _zip({"../secret.md": "# Secret\nNope"})

    with pytest.raises(Exception, match="unsafe archive path"):
        service.preview_zip(data)


def test_notion_export_rejects_non_zip_and_empty_markdown_archive(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(Exception, match="valid Notion ZIP"):
        service.preview_zip(b"not a zip")
    with pytest.raises(Exception, match="no importable Markdown"):
        service.preview_zip(_zip({"assets/readme.txt": "hello"}))


def test_notion_export_rejects_oversized_markdown_before_ingest(tmp_path):
    fake = FakeIngest()
    service = _service(tmp_path, fake)
    data = _zip({"Huge.md": "# Huge\n" + ("x" * (5 * 1024 * 1024))})

    with pytest.raises(Exception, match="too large"):
        service.ingest_zip(data, user_id="tenant-a")

    assert fake.calls == []


def test_notion_connector_is_registered():
    registry = ConnectorRegistry()
    assert "notion.v1" in registry.list_connectors()
    assert registry.get("notion.v1").connector_id == "notion.v1"

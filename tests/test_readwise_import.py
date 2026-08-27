from __future__ import annotations

from app.config import Settings
from app.models.video import IngestResultItem
from app.services.readwise_import_service import ReadwiseImportService
from app.services.sources import ConnectorRegistry
from app.services.sources.readwise_connector import ReadwiseConnector


CSV = b'''Highlight,Title,Author,URL,Note,Location,Tags,Document tags\n"First idea","Article A","Ada","https://example.com/a","use this","10","ai,rag","research"\n"Second idea","Article A","Ada","https://example.com/a","","20","rag",""\n"Only idea","Article B","Bob","","remember","5","python","learning"\n'''


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
            chunk_count=len(kwargs["ref_extra"]["highlights"]),
        )


def test_readwise_csv_groups_highlights_and_preserves_tags(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "db.sqlite"), chroma_persist_dir=str(tmp_path / "chroma"))
    fake = FakeIngest()
    service = ReadwiseImportService(settings, ingest_service=fake)

    preview = service.preview_csv(CSV)

    assert preview["article_count"] == 2
    assert preview["highlight_count"] == 3
    first = preview["articles"][0]
    assert first["title"] == "Article A"
    assert first["highlight_count"] == 2
    assert set(first["tags"]) == {"ai", "rag", "research"}

    result = service.ingest_csv(CSV, user_id="user-a")
    assert result["article_count"] == 2
    assert result["highlight_count"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert len(fake.calls) == 2
    assert all(call["user_id"] == "user-a" for call in fake.calls)
    assert all(call["connector_id"] == "readwise.v1" for call in fake.calls)
    assert fake.calls[0]["ref_extra"]["highlights"] == ["First idea", "Second idea"]
    assert "Readwise" in fake.calls[0]["reflection"].reflection_note


def test_readwise_connector_turns_each_highlight_into_evidence_segment():
    connector = ReadwiseConnector()
    ref = connector.parse_ref("readwise://article/abc123")
    ref.extra.update(
        {
            "title": "Article A",
            "author": "Ada",
            "canonical_url": "https://example.com/a",
            "highlights": ["First idea", "Second idea"],
            "notes": ["my note", ""],
            "locations": ["10", "20"],
            "tags": ["rag"],
        }
    )

    item = connector.fetch_metadata(ref)
    transcript = connector.fetch_transcript(ref)

    assert item.connector_id == "readwise.v1"
    assert item.canonical_url == "https://example.com/a"
    assert item.raw_metadata["highlight_count"] == 2
    assert len(transcript.segments) == 2
    assert transcript.segments[0].text == "First idea\nNote: my note"
    assert transcript.segments[1].text == "Second idea"


def test_readwise_connector_is_registered():
    registry = ConnectorRegistry()
    assert "readwise.v1" in registry.list_connectors()
    assert registry.get("readwise.v1").connector_id == "readwise.v1"


def test_readwise_csv_rejects_missing_required_columns(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "db.sqlite"), chroma_persist_dir=str(tmp_path / "chroma"))
    service = ReadwiseImportService(settings, ingest_service=FakeIngest())

    try:
        service.parse_csv(b"Title,Author\nArticle,Ada\n")
    except Exception as exc:
        assert "Highlight and Title" in str(exc)
    else:
        raise AssertionError("invalid Readwise CSV should fail")

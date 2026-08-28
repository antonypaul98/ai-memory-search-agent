from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.services.gdrive_import_service import (
    DRIVE_READONLY_SCOPE,
    GoogleDriveImportService,
)
from app.services.oauth_token_vault import OAuthTokenRecord
from app.services.sources import ConnectorRegistry
from app.services.sources.gdrive_connector import GoogleDriveConnector


class FakeVault:
    def __init__(self, records: dict[str, OAuthTokenRecord]) -> None:
        self.records = records
        self.calls: list[tuple[str, str]] = []

    def get(self, *, user_id: str, connector_id: str, audit_use: bool = True):
        self.calls.append((user_id, connector_id))
        return self.records.get(user_id)


def _record(user_id: str, *, scopes=(DRIVE_READONLY_SCOPE,), expired: bool = False) -> OAuthTokenRecord:
    return OAuthTokenRecord(
        user_id=user_id,
        connector_id="gdrive.v1",
        access_token=f"token-{user_id}",
        refresh_token="refresh",
        scopes=tuple(scopes),
        expires_at=datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=1)),
        enabled=True,
    )


def test_registry_contains_google_drive_connector():
    registry = ConnectorRegistry()
    assert "gdrive.v1" in registry.list_connectors()
    assert registry.resolve_for_url("gdrive://file/abc123").connector_id == "gdrive.v1"


def test_connector_preserves_drive_provenance_and_text():
    connector = GoogleDriveConnector()
    ref = connector.parse_ref("gdrive://file/file-123")
    ref.extra = {
        "name": "Architecture Notes",
        "mime_type": "application/vnd.google-apps.document",
        "modified_time": "2026-08-27T10:00:00Z",
        "web_view_link": "https://drive.google.com/file/d/file-123/view",
        "provider_checksum": "checksum",
        "text": "Canonical records preserve provenance. Evidence remains attributable.",
    }
    item = connector.fetch_metadata(ref)
    transcript = connector.fetch_transcript(ref)

    assert item.external_id == "file-123"
    assert item.connector_id == "gdrive.v1"
    assert item.raw_metadata["drive_file_id"] == "file-123"
    assert item.raw_metadata["provider_checksum"] == "checksum"
    assert transcript.full_text.startswith("Canonical records")
    assert transcript.segments


def test_list_files_is_tenant_scoped_and_deduplicates_provider_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token-user-a"
        return httpx.Response(
            200,
            json={
                "files": [
                    {"id": "1", "name": "Doc", "mimeType": "application/vnd.google-apps.document"},
                    {"id": "1", "name": "Doc duplicate", "mimeType": "application/vnd.google-apps.document"},
                    {"id": "2", "name": "Paper", "mimeType": "application/pdf"},
                ],
                "nextPageToken": "next",
            },
        )

    vault = FakeVault({"user-a": _record("user-a"), "user-b": _record("user-b")})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = GoogleDriveImportService(Settings(), vault=vault, client=client)

    result = service.list_files(user_id="user-a")

    assert [item["file_id"] for item in result["files"]] == ["1", "2"]
    assert result["next_page_token"] == "next"
    assert vault.calls == [("user-a", "gdrive.v1")]


def test_missing_scope_and_expired_token_fail_closed():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    missing_scope = GoogleDriveImportService(
        Settings(),
        vault=FakeVault({"u": _record("u", scopes=("profile",))}),
        client=client,
    )
    with pytest.raises(AppError, match="read-only scope"):
        missing_scope.list_files(user_id="u")

    expired = GoogleDriveImportService(
        Settings(),
        vault=FakeVault({"u": _record("u", expired=True)}),
        client=client,
    )
    with pytest.raises(AppError, match="expired"):
        expired.list_files(user_id="u")


def test_import_google_doc_routes_extracted_text_through_universal_connector(monkeypatch):
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path.endswith("/file-1"):
            return httpx.Response(
                200,
                json={
                    "id": "file-1",
                    "name": "Design doc",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-08-27T12:00:00Z",
                    "webViewLink": "https://drive.google.com/file/d/file-1/view",
                },
            )
        if request.url.path.endswith("/file-1/export"):
            return httpx.Response(200, content=b"Design evidence from Google Docs.")
        raise AssertionError(request.url)

    captured = {}

    class FakeIngest:
        def __init__(self, settings):
            pass

        def ingest_url(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return SimpleNamespace(success=True, skipped=False, chunk_count=1, error=None, title="Design doc")

    monkeypatch.setattr("app.services.gdrive_import_service.ConnectorIngestService", FakeIngest)
    service = GoogleDriveImportService(
        Settings(),
        vault=FakeVault({"tenant": _record("tenant")}),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = service.import_file(user_id="tenant", file_id="file-1")

    assert result["success"] is True
    assert captured["url"] == "gdrive://file/file-1"
    assert captured["user_id"] == "tenant"
    assert captured["connector_id"] == "gdrive.v1"
    assert captured["ref_extra"]["text"] == "Design evidence from Google Docs."
    assert captured["ref_extra"]["content_hash"]


def test_import_pdf_downloads_media_and_extracts_text(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pdf-1") and request.url.params.get("alt") != "media":
            return httpx.Response(200, json={"id": "pdf-1", "name": "Paper", "mimeType": "application/pdf"})
        if request.url.path.endswith("/pdf-1") and request.url.params.get("alt") == "media":
            return httpx.Response(200, content=b"%PDF-fixture")
        raise AssertionError(request.url)

    monkeypatch.setattr("app.services.gdrive_import_service._extract_pdf_text", lambda data: "Extracted PDF evidence")

    class FakeIngest:
        def __init__(self, settings):
            pass

        def ingest_url(self, url, **kwargs):
            assert kwargs["ref_extra"]["mime_type"] == "application/pdf"
            assert kwargs["ref_extra"]["text"] == "Extracted PDF evidence"
            return SimpleNamespace(success=True, skipped=False, chunk_count=2, error=None, title="Paper")

    monkeypatch.setattr("app.services.gdrive_import_service.ConnectorIngestService", FakeIngest)
    service = GoogleDriveImportService(
        Settings(),
        vault=FakeVault({"tenant": _record("tenant")}),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = service.import_file(user_id="tenant", file_id="pdf-1")
    assert result["success"] is True
    assert result["chunk_count"] == 2


def test_unsupported_drive_type_is_rejected_before_ingest():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "sheet-1", "name": "Sheet", "mimeType": "application/vnd.google-apps.spreadsheet"})

    service = GoogleDriveImportService(
        Settings(),
        vault=FakeVault({"tenant": _record("tenant")}),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AppError, match="Docs and PDFs only"):
        service.import_file(user_id="tenant", file_id="sheet-1")

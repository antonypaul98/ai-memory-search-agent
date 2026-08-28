"""Tenant-scoped Google Drive discovery and Docs/PDF import."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from typing import Callable

import httpx
from pypdf import PdfReader

from app.config import Settings
from app.core.exceptions import AppError
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.oauth_token_vault import OAuthTokenRecord, OAuthTokenVault, RefreshCallback

CONNECTOR_ID = "gdrive.v1"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_GOOGLE_DOC = "application/vnd.google-apps.document"
_PDF = "application/pdf"
_FILES_URL = "https://www.googleapis.com/drive/v3/files"


class GoogleDriveImportService:
    """Read only the authenticated user's selected Google Drive content."""

    def __init__(
        self,
        settings: Settings,
        *,
        vault: OAuthTokenVault | None = None,
        client: httpx.Client | None = None,
        refresh: RefreshCallback | None = None,
    ) -> None:
        self._settings = settings
        self._vault = vault or OAuthTokenVault(settings)
        self._client = client
        self._refresh = refresh

    def list_files(self, *, user_id: str, limit: int = 25, page_token: str = "") -> dict:
        if limit < 1 or limit > 100:
            raise AppError("Google Drive preview limit must be between 1 and 100.")
        token = self._token(user_id)
        params = {
            "pageSize": limit,
            "q": "trashed=false and (mimeType='application/vnd.google-apps.document' or mimeType='application/pdf')",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,md5Checksum,size)",
            "orderBy": "modifiedTime desc",
        }
        if page_token.strip():
            params["pageToken"] = page_token.strip()
        payload = self._request_json("GET", _FILES_URL, token.access_token, params=params)
        files = [self._normalize_metadata(item) for item in payload.get("files", []) if isinstance(item, dict)]
        # Provider file IDs are canonical. Collapse duplicates deterministically in case a mock/proxy repeats rows.
        deduped = {item["file_id"]: item for item in files if item["file_id"]}
        return {
            "connector_id": CONNECTOR_ID,
            "files": list(deduped.values()),
            "next_page_token": str(payload.get("nextPageToken") or ""),
        }

    def import_file(self, *, user_id: str, file_id: str, force_refresh: bool = False) -> dict:
        file_id = (file_id or "").strip()
        if not file_id or "/" in file_id:
            raise AppError("A valid Google Drive file id is required.")
        token = self._token(user_id)
        fields = "id,name,mimeType,modifiedTime,webViewLink,md5Checksum,size"
        raw_meta = self._request_json("GET", f"{_FILES_URL}/{file_id}", token.access_token, params={"fields": fields})
        meta = self._normalize_metadata(raw_meta)
        mime_type = meta["mime_type"]
        if mime_type == _GOOGLE_DOC:
            body = self._request_bytes(
                "GET",
                f"{_FILES_URL}/{file_id}/export",
                token.access_token,
                params={"mimeType": "text/plain"},
            )
            text = body.decode("utf-8", errors="replace").strip()
        elif mime_type == _PDF:
            body = self._request_bytes(
                "GET",
                f"{_FILES_URL}/{file_id}",
                token.access_token,
                params={"alt": "media"},
            )
            text = _extract_pdf_text(body)
        else:
            raise AppError("Google Drive connector supports Google Docs and PDFs only.")
        if not text.strip():
            raise AppError("Google Drive file has no extractable text.")

        content_hash = sha256(body).hexdigest()
        extra = {
            "name": meta["name"],
            "mime_type": mime_type,
            "modified_time": meta["modified_time"],
            "web_view_link": meta["web_view_link"],
            "provider_checksum": meta["provider_checksum"],
            "content_hash": content_hash,
            "text": text,
        }
        result = ConnectorIngestService(self._settings).ingest_url(
            f"gdrive://file/{file_id}",
            user_id=user_id,
            force_refresh=force_refresh,
            connector_id=CONNECTOR_ID,
            ref_extra=extra,
        )
        return {
            "file_id": file_id,
            "title": result.title or meta["name"],
            "success": result.success,
            "skipped": result.skipped,
            "chunk_count": result.chunk_count,
            "error": result.error,
        }

    def _token(self, user_id: str) -> OAuthTokenRecord:
        user_id = (user_id or "").strip()
        if not user_id:
            raise AppError("Authenticated user is required.")
        try:
            if self._refresh is not None:
                record = self._vault.get_valid(
                    user_id=user_id,
                    connector_id=CONNECTOR_ID,
                    refresh=self._refresh,
                )
            else:
                record = self._vault.get(user_id=user_id, connector_id=CONNECTOR_ID)
        except (LookupError, RuntimeError) as exc:
            raise AppError("Google Drive authorization is unavailable or expired.") from exc
        if record is None or record.expired:
            raise AppError("Google Drive authorization is unavailable or expired.")
        if DRIVE_READONLY_SCOPE not in record.scopes:
            raise AppError("Google Drive connection is missing the required read-only scope.")
        return record

    def _request_json(self, method: str, url: str, token: str, *, params: dict) -> dict:
        response = self._request(method, url, token, params=params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError("Google Drive returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise AppError("Google Drive returned an invalid response.")
        return payload

    def _request_bytes(self, method: str, url: str, token: str, *, params: dict) -> bytes:
        response = self._request(method, url, token, params=params)
        body = response.content
        if len(body) > self._settings.capture_max_response_bytes:
            raise AppError("Google Drive file exceeds the configured import size limit.")
        return body

    def _request(self, method: str, url: str, token: str, *, params: dict) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            if self._client is not None:
                response = self._client.request(method, url, headers=headers, params=params)
            else:
                with httpx.Client(timeout=self._settings.capture_fetch_timeout_sec, follow_redirects=False) as client:
                    response = client.request(method, url, headers=headers, params=params)
            if response.status_code in {401, 403}:
                raise AppError("Google Drive authorization was rejected.")
            response.raise_for_status()
            return response
        except AppError:
            raise
        except httpx.HTTPError as exc:
            raise AppError("Google Drive request failed.") from exc

    @staticmethod
    def _normalize_metadata(item: dict) -> dict:
        return {
            "file_id": str(item.get("id") or "").strip(),
            "name": str(item.get("name") or "Google Drive file").strip(),
            "mime_type": str(item.get("mimeType") or "").strip(),
            "modified_time": str(item.get("modifiedTime") or "").strip(),
            "web_view_link": str(item.get("webViewLink") or "").strip(),
            "provider_checksum": str(item.get("md5Checksum") or "").strip(),
            "size": str(item.get("size") or "").strip(),
        }


def _extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    except Exception as exc:
        raise AppError("Google Drive PDF could not be parsed.") from exc

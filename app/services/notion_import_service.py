"""Safe offline importer for Notion Markdown export ZIP files.

The archive is parsed entirely in memory; files are never extracted to disk. This avoids
zip-slip path traversal while preserving the original export path as provenance.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import PurePosixPath

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.reflection import ReflectionInput, SaveReason
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.deduplication_service import hash_text

_MAX_FILES = 2000
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
_UUID_SUFFIX = re.compile(r"\s+[0-9a-fA-F]{32}$")


class NotionImportService:
    def __init__(
        self,
        settings: Settings | None = None,
        ingest_service: ConnectorIngestService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._ingest = ingest_service or ConnectorIngestService(self._settings)

    def parse_zip(self, data: bytes) -> list[dict]:
        if not data:
            raise AppError("Notion export ZIP is empty.")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError) as exc:
            raise AppError("Upload must be a valid Notion ZIP export.") from exc

        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > _MAX_FILES:
            raise AppError(f"Notion export contains too many files (max {_MAX_FILES}).")
        total_size = sum(max(0, info.file_size) for info in infos)
        if total_size > _MAX_UNCOMPRESSED_BYTES:
            raise AppError("Notion export is too large after decompression (max 100MB).")

        pages: list[dict] = []
        seen_hashes: set[str] = set()
        for info in infos:
            path = _safe_archive_path(info.filename)
            if path.suffix.lower() not in {".md", ".markdown"}:
                continue
            if info.file_size > _MAX_FILE_BYTES:
                raise AppError(f"Notion Markdown page is too large: {path.as_posix()}")
            raw = archive.read(info)
            try:
                markdown = raw.decode("utf-8-sig").strip()
            except UnicodeDecodeError as exc:
                raise AppError(f"Notion Markdown must be UTF-8: {path.as_posix()}") from exc
            if not markdown:
                continue
            content_hash = hash_text(markdown)
            # Notion exports can contain duplicate linked copies. Preserve one canonical
            # record per identical page content deterministically.
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            title = _page_title(markdown, path)
            stable_material = f"{path.as_posix()}\n{content_hash}"
            external_id = hash_text(stable_material)[:24]
            pages.append(
                {
                    "external_id": external_id,
                    "title": title,
                    "export_path": path.as_posix(),
                    "markdown": markdown,
                    "content_hash": content_hash,
                }
            )

        if not pages:
            raise AppError("Notion export contains no importable Markdown pages.")
        pages.sort(key=lambda page: (page["export_path"].lower(), page["external_id"]))
        return pages

    def preview_zip(self, data: bytes) -> dict:
        pages = self.parse_zip(data)
        return {
            "page_count": len(pages),
            "pages": [
                {
                    "external_id": page["external_id"],
                    "title": page["title"],
                    "export_path": page["export_path"],
                    "content_hash": page["content_hash"],
                }
                for page in pages[:200]
            ],
        }

    def ingest_zip(self, data: bytes, *, user_id: str, force_refresh: bool = False) -> dict:
        pages = self.parse_zip(data)
        results = []
        for page in pages:
            reflection = ReflectionInput(
                save_reason=SaveReason.REFERENCE,
                reflection_note="Imported from a Notion export.",
            )
            result = self._ingest.ingest_url(
                f"notion://page/{page['external_id']}",
                user_id=user_id,
                force_refresh=force_refresh,
                reflection=reflection,
                connector_id="notion.v1",
                ref_extra=page,
            )
            results.append(result)
        return {
            "page_count": len(pages),
            "succeeded": sum(1 for result in results if result.success and not result.skipped),
            "skipped": sum(1 for result in results if result.skipped),
            "failed": sum(1 for result in results if not result.success),
            "results": [result.model_dump(mode="json") for result in results],
        }


def _safe_archive_path(name: str) -> PurePosixPath:
    normalized = (name or "").replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or any(part in {"", ".", ".."} for part in path.parts):
        raise AppError("Notion export contains an unsafe archive path.")
    return path


def _page_title(markdown: str, path: PurePosixPath) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and stripped[2:].strip():
            return stripped[2:].strip()[:500]
    stem = _UUID_SUFFIX.sub("", path.stem).strip()
    return (stem or "Untitled Notion page")[:500]

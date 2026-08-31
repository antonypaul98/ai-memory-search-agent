"""Unified import manager — queue/run/history for all connectors."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.bookmark_store_factory import get_bookmark_store
from app.db.import_run_store_factory import get_import_run_store
from app.models.capture import BookmarkImportRequest
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.cross_duplicate_service import CrossConnectorDuplicateDetector
from app.services.deduplication_service import hash_text
from app.services.ingest_service import IngestService
from app.services.sources import get_connector_registry
from app.services.sources.bookmark_connector import BookmarkConnector
from app.utils.url_parser import is_valid_youtube_url


class ImportManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._connector_ingest = ConnectorIngestService(self._settings)
        self._youtube_ingest = IngestService(settings=self._settings)
        self._dupes = CrossConnectorDuplicateDetector(self._settings)
        self._bookmarks = get_bookmark_store(self._settings)
        self._imports = get_import_run_store(self._settings)

    def create_import(self, *, user_id: str, connector_id: str, urls: list[str], titles: list[str] | None = None) -> dict:
        import_id = str(uuid.uuid4())
        now = _now()
        titles = titles or [""] * len(urls)
        self._imports.create(
            import_id=import_id,
            user_id=user_id,
            connector_id=connector_id,
            items=list(zip(urls, titles)),
            now=now,
        )
        return self.get_import(import_id, user_id=user_id)

    def start_import_async(self, import_id: str, *, user_id: str) -> dict:
        thread = threading.Thread(
            target=self._run_import,
            args=(import_id, user_id),
            daemon=True,
            name=f"import-{import_id[:8]}",
        )
        thread.start()
        return self.get_import(import_id, user_id=user_id)

    def cancel_import(self, import_id: str, *, user_id: str) -> dict:
        run = self.get_import(import_id, user_id=user_id)
        if run["status"] in {"completed", "cancelled"}:
            return run
        self._set_run(import_id, user_id=user_id, status="cancelled", detail="Cancelled by user")
        self._imports.cancel_items(import_id=import_id, user_id=user_id, now=_now())
        return self.get_import(import_id, user_id=user_id)

    def _is_cancelled(self, import_id: str, *, user_id: str) -> bool:
        return self._imports.is_cancelled(import_id=import_id, user_id=user_id)

    def preview_bookmarks(self, payload: BookmarkImportRequest, *, user_id: str) -> dict:
        connector = get_connector_registry().get("bookmarks.v1")
        assert isinstance(connector, BookmarkConnector)
        known = self._dupes.known_url_hashes(user_id)
        items = [i.model_dump() for i in payload.items]
        preview = connector.preview_import(items, known_url_hashes=known)
        preview["connector_id"] = "bookmarks.v1"
        preview["snapshot_complete"] = payload.snapshot_complete
        return preview

    def import_bookmarks(self, payload: BookmarkImportRequest, *, user_id: str, async_processing: bool = True) -> dict:
        preview = self.preview_bookmarks(payload, user_id=user_id)
        now = _now()
        bookmark_items = [
            {
                "browser_bookmark_id": item.browser_bookmark_id,
                "folder_path": item.folder_path,
                "url": item.url,
                "url_hash": hash_text(item.url),
                "title": item.title,
            }
            for item in payload.items
        ]
        self._bookmarks.sync_snapshot(
            user_id=user_id,
            source_browser=payload.source_browser,
            items=bookmark_items,
            snapshot_complete=payload.snapshot_complete,
            now=now,
        )

        urls = [i.url for i in payload.items if i.url.startswith("http")]
        titles = [i.title for i in payload.items if i.url.startswith("http")]
        run = self.create_import(user_id=user_id, connector_id="bookmarks.v1", urls=urls, titles=titles)
        if async_processing and urls:
            self.start_import_async(run["import_id"], user_id=user_id)
        else:
            self._run_import(run["import_id"], user_id)
        result = self.get_import(run["import_id"], user_id=user_id)
        result["preview"] = preview
        result["sync_mode"] = payload.sync_mode
        result["snapshot_complete"] = payload.snapshot_complete
        return result

    def list_imports(self, *, user_id: str, limit: int = 50) -> list[dict]:
        return self._imports.list(user_id=user_id, limit=limit)

    def get_import(self, import_id: str, *, user_id: str, item_limit: int = 200) -> dict:
        return self._imports.get(import_id=import_id, user_id=user_id, item_limit=item_limit)

    def connector_health(self) -> list[dict]:
        return get_connector_registry().health_all()

    def _run_import(self, import_id: str, user_id: str) -> None:
        self._set_run(import_id, user_id=user_id, status="running", detail="Import in progress")
        items = self._imports.list_pending_items(import_id=import_id, user_id=user_id)
        completed = failed = skipped = duplicates = unsupported = 0
        for item in items:
            if self._is_cancelled(import_id, user_id=user_id):
                self._set_run(
                    import_id,
                    user_id=user_id,
                    status="cancelled",
                    detail="Cancelled by user",
                    completed_items=completed,
                    failed_items=failed,
                    skipped_items=skipped,
                    duplicate_items=duplicates,
                    unsupported_items=unsupported,
                )
                return
            url = item["url"]
            item_id = item["id"]
            try:
                if not url.startswith("http"):
                    unsupported += 1
                    self._set_item(item_id, user_id=user_id, status="unsupported", detail="Unsupported URL")
                    continue
                dupe = self._dupes.check(user_id=user_id, canonical_url=url)
                if dupe.is_duplicate:
                    duplicates += 1
                    skipped += 1
                    self._set_item(item_id, user_id=user_id, status="duplicate", detail=dupe.reason)
                    continue
                self._set_item(item_id, user_id=user_id, status="processing", detail="Indexing…")
                if is_valid_youtube_url(url):
                    result = self._youtube_ingest.ingest_single_url(url, user_id=user_id)
                else:
                    result = self._connector_ingest.ingest_url(url, user_id=user_id)
                if result.skipped:
                    skipped += 1
                    duplicates += 1
                    self._set_item(item_id, user_id=user_id, status="duplicate", detail="Already indexed", external_id=result.video_id or "")
                elif result.success:
                    completed += 1
                    if result.webpage_url or url:
                        self._dupes.register(
                            user_id=user_id,
                            canonical_url=result.webpage_url or url,
                            content_hash="",
                            source_type="youtube" if is_valid_youtube_url(url) else "web",
                            connector_id="youtube.v1" if is_valid_youtube_url(url) else "web.v1",
                            external_id=result.video_id or "",
                        )
                    self._set_item(item_id, user_id=user_id, status="completed", detail=f"{result.chunk_count or 0} chunks", external_id=result.video_id or "")
                else:
                    failed += 1
                    self._set_item(item_id, user_id=user_id, status="failed", error=result.error or "failed")
            except Exception as exc:
                failed += 1
                self._set_item(item_id, user_id=user_id, status="failed", error=str(exc))

        if self._is_cancelled(import_id, user_id=user_id):
            self._set_run(
                import_id,
                user_id=user_id,
                status="cancelled",
                detail="Cancelled by user",
                completed_items=completed,
                failed_items=failed,
                skipped_items=skipped,
                duplicate_items=duplicates,
                unsupported_items=unsupported,
            )
            return

        status = "completed" if failed == 0 else ("partial" if completed else "failed")
        self._set_run(
            import_id,
            user_id=user_id,
            status=status,
            detail="Import finished",
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
            duplicate_items=duplicates,
            unsupported_items=unsupported,
        )

    def _set_run(self, import_id: str, *, user_id: str, **fields) -> None:
        self._imports.update_run(import_id=import_id, user_id=user_id, fields=fields, now=_now())

    def _set_item(self, item_id: int, *, user_id: str, status: str, detail: str = "", error: str | None = None, external_id: str = "") -> None:
        self._imports.update_item(
            item_id=item_id,
            user_id=user_id,
            status=status,
            detail=detail,
            error=error,
            external_id=external_id,
            now=_now(),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

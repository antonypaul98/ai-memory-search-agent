"""Unified import manager — queue/run/history for all connectors."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate
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
        migrate(self._settings)

    def create_import(
        self,
        *,
        user_id: str,
        connector_id: str,
        urls: list[str],
        titles: list[str] | None = None,
    ) -> dict:
        import_id = str(uuid.uuid4())
        now = _now()
        titles = titles or [""] * len(urls)
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO import_runs (
                    import_id, user_id, connector_id, status, total_items,
                    completed_items, failed_items, skipped_items, duplicate_items,
                    unsupported_items, detail, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, 0, 0, 0, 0, 0, '', ?, ?)
                """,
                (import_id, user_id, connector_id, len(urls), now, now),
            )
            for url, title in zip(urls, titles):
                conn.execute(
                    """
                    INSERT INTO import_run_items (
                        import_id, user_id, url, title, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (import_id, user_id, url, title or "", now, now),
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
        self._set_run(import_id, status="cancelled", detail="Cancelled by user")
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                UPDATE import_run_items
                SET status = 'cancelled', detail = 'Cancelled', updated_at = ?
                WHERE import_id = ? AND status IN ('queued', 'processing')
                """,
                (_now(), import_id),
            )
        return self.get_import(import_id, user_id=user_id)

    def _is_cancelled(self, import_id: str) -> bool:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT status FROM import_runs WHERE import_id = ?",
                (import_id,),
            ).fetchone()
        return bool(row and row["status"] == "cancelled")

    def preview_bookmarks(self, payload: BookmarkImportRequest, *, user_id: str) -> dict:
        connector = get_connector_registry().get("bookmarks.v1")
        assert isinstance(connector, BookmarkConnector)
        known = self._dupes.known_url_hashes(user_id)
        items = [i.model_dump() for i in payload.items]
        preview = connector.preview_import(items, known_url_hashes=known)
        preview["connector_id"] = "bookmarks.v1"
        preview["snapshot_complete"] = payload.snapshot_complete
        return preview

    def import_bookmarks(
        self,
        payload: BookmarkImportRequest,
        *,
        user_id: str,
        async_processing: bool = True,
    ) -> dict:
        preview = self.preview_bookmarks(payload, user_id=user_id)
        now = _now()
        current_ids = {item.browser_bookmark_id for item in payload.items}

        # Reconcile browser state only when the client explicitly guarantees that
        # this payload is a complete snapshot. This prevents truncated/partial
        # imports from falsely marking unseen browser bookmarks as deleted.
        with get_connection(self._settings) as conn:
            if payload.snapshot_complete:
                if current_ids:
                    placeholders = ",".join("?" for _ in current_ids)
                    conn.execute(
                        f"""
                        UPDATE browser_bookmarks
                        SET removed_in_browser = 1, sync_status = 'removed', last_synced_at = ?
                        WHERE user_id = ? AND source_browser = ?
                          AND browser_bookmark_id NOT IN ({placeholders})
                        """,
                        (now, user_id, payload.source_browser, *sorted(current_ids)),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE browser_bookmarks
                        SET removed_in_browser = 1, sync_status = 'removed', last_synced_at = ?
                        WHERE user_id = ? AND source_browser = ?
                        """,
                        (now, user_id, payload.source_browser),
                    )

            for item in payload.items:
                conn.execute(
                    """
                    INSERT INTO browser_bookmarks (
                        user_id, browser_bookmark_id, folder_path, url, url_hash, title,
                        sync_status, source_browser, last_synced_at, removed_in_browser
                    ) VALUES (?, ?, ?, ?, ?, ?, 'synced', ?, ?, 0)
                    ON CONFLICT(user_id, browser_bookmark_id) DO UPDATE SET
                        folder_path = excluded.folder_path,
                        url = excluded.url,
                        url_hash = excluded.url_hash,
                        title = excluded.title,
                        sync_status = 'synced',
                        source_browser = excluded.source_browser,
                        last_synced_at = excluded.last_synced_at,
                        removed_in_browser = 0
                    """,
                    (
                        user_id,
                        item.browser_bookmark_id,
                        item.folder_path,
                        item.url,
                        hash_text(item.url),
                        item.title,
                        payload.source_browser,
                        now,
                    ),
                )

        urls = [i.url for i in payload.items if i.url.startswith("http")]
        titles = [i.title for i in payload.items if i.url.startswith("http")]
        run = self.create_import(
            user_id=user_id, connector_id="bookmarks.v1", urls=urls, titles=titles
        )
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
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM import_runs WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_import(self, import_id: str, *, user_id: str, item_limit: int = 200) -> dict:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM import_runs WHERE import_id = ? AND user_id = ?",
                (import_id, user_id),
            ).fetchone()
            if not row:
                raise KeyError("Import not found")
            items = conn.execute(
                """
                SELECT url, title, status, detail, error, external_id
                FROM import_run_items WHERE import_id = ? ORDER BY id ASC
                LIMIT ?
                """,
                (import_id, item_limit),
            ).fetchall()
            total_items_row = conn.execute(
                "SELECT COUNT(*) AS c FROM import_run_items WHERE import_id = ?",
                (import_id,),
            ).fetchone()
        data = dict(row)
        data["items"] = [dict(i) for i in items]
        data["items_returned"] = len(data["items"])
        data["items_total"] = int(total_items_row["c"] if total_items_row else 0)
        return data

    def connector_health(self) -> list[dict]:
        return get_connector_registry().health_all()

    def _run_import(self, import_id: str, user_id: str) -> None:
        self._set_run(import_id, status="running", detail="Import in progress")
        with get_connection(self._settings) as conn:
            items = conn.execute(
                "SELECT id, url, title FROM import_run_items WHERE import_id = ?",
                (import_id,),
            ).fetchall()
        completed = failed = skipped = duplicates = unsupported = 0
        for item in items:
            if self._is_cancelled(import_id):
                self._set_run(
                    import_id,
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
                    self._set_item(item_id, status="unsupported", detail="Unsupported URL")
                    continue
                dupe = self._dupes.check(user_id=user_id, canonical_url=url)
                if dupe.is_duplicate:
                    duplicates += 1
                    skipped += 1
                    self._set_item(item_id, status="duplicate", detail=dupe.reason)
                    continue
                self._set_item(item_id, status="processing", detail="Indexing…")
                if is_valid_youtube_url(url):
                    result = self._youtube_ingest.ingest_single_url(url, user_id=user_id)
                else:
                    result = self._connector_ingest.ingest_url(url, user_id=user_id)
                if result.skipped:
                    skipped += 1
                    duplicates += 1
                    self._set_item(
                        item_id,
                        status="duplicate",
                        detail="Already indexed",
                        external_id=result.video_id or "",
                    )
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
                    self._set_item(
                        item_id,
                        status="completed",
                        detail=f"{result.chunk_count or 0} chunks",
                        external_id=result.video_id or "",
                    )
                else:
                    failed += 1
                    self._set_item(item_id, status="failed", error=result.error or "failed")
            except Exception as exc:
                failed += 1
                self._set_item(item_id, status="failed", error=str(exc))

        if self._is_cancelled(import_id):
            self._set_run(
                import_id,
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
            status=status,
            detail="Import finished",
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
            duplicate_items=duplicates,
            unsupported_items=unsupported,
        )

    def _set_run(self, import_id: str, **fields) -> None:
        allowed = {
            "status",
            "detail",
            "error",
            "completed_items",
            "failed_items",
            "skipped_items",
            "duplicate_items",
            "unsupported_items",
        }
        sets = []
        values = []
        for key, value in fields.items():
            if key in allowed:
                sets.append(f"{key} = ?")
                values.append(value)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(import_id)
        with get_connection(self._settings) as conn:
            conn.execute(
                f"UPDATE import_runs SET {', '.join(sets)} WHERE import_id = ?",
                values,
            )

    def _set_item(
        self,
        item_id: int,
        *,
        status: str,
        detail: str = "",
        error: str | None = None,
        external_id: str = "",
    ) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                UPDATE import_run_items
                SET status = ?, detail = ?, error = ?, external_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, detail, error, external_id, _now(), item_id),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

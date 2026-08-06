"""Capture URLs and bookmarks for the AI Memory Agent extension and web clients."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate
from app.models.capture import (
    BookmarkImportRequest,
    CaptureBatchRequest,
    CaptureStatusResponse,
    CaptureUrlRequest,
)
from app.models.reflection import ReflectionInput, SaveReason
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.deduplication_service import hash_text
from app.services.import_manager import ImportManager
from app.services.ingest_service import IngestService
from app.utils.url_parser import is_valid_youtube_url

logger = logging.getLogger(__name__)


class CaptureService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._ingest = IngestService(settings=self._settings)
        self._connector_ingest = ConnectorIngestService(self._settings)
        self._imports = ImportManager(self._settings)
        migrate(self._settings)

    def capture_url(self, payload: CaptureUrlRequest, *, user_id: str) -> CaptureStatusResponse:
        capture_id = str(uuid.uuid4())
        now = _utc_now()
        url = payload.url.strip()
        title = payload.title.strip()
        if payload.observed:
            if not title:
                title = str(payload.observed.extra.get("title") or "").strip()
            if payload.observed.description and not payload.page_description:
                payload = payload.model_copy(
                    update={"page_description": payload.observed.description[:500]}
                )
        if title and not payload.title:
            payload = payload.model_copy(update={"title": title})
        title = payload.title

        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO captures (
                    capture_id, user_id, url, url_hash, title, source_type, status,
                    stage, stage_detail, payload_json, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    user_id,
                    url,
                    hash_text(url),
                    title,
                    payload.source_type,
                    "queued",
                    "queued",
                    "Added to Memory",
                    payload.model_dump_json(),
                    None,
                    now,
                    now,
                ),
            )

        if payload.async_processing:
            thread = threading.Thread(
                target=self._process_capture_async,
                args=(capture_id, user_id, payload),
                daemon=True,
                name=f"capture-{capture_id[:8]}",
            )
            thread.start()
            return CaptureStatusResponse(
                capture_id=capture_id,
                status="queued",
                stage="queued",
                stage_detail="Added to Memory",
                url=url,
                title=title,
                message="Added to Memory — processing…",
            )

        return self._process_capture_sync(capture_id, user_id, payload)

    def retry_capture(self, capture_id: str, *, user_id: str) -> CaptureStatusResponse:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT payload_json, status FROM captures WHERE capture_id = ? AND user_id = ?",
                (capture_id, user_id),
            ).fetchone()
        if not row:
            raise KeyError("Capture not found")
        payload = CaptureUrlRequest.model_validate_json(row["payload_json"])
        self._update_stage(capture_id, user_id, status="queued", stage="queued", detail="Retrying…")
        if payload.async_processing:
            thread = threading.Thread(
                target=self._process_capture_async,
                args=(capture_id, user_id, payload),
                daemon=True,
                name=f"capture-retry-{capture_id[:8]}",
            )
            thread.start()
            return self.get_status(capture_id, user_id=user_id)
        return self._process_capture_sync(capture_id, user_id, payload)

    def capture_batch(self, payload: CaptureBatchRequest, *, user_id: str) -> list[CaptureStatusResponse]:
        items = payload.items
        if payload.dedupe:
            seen: set[str] = set()
            unique = []
            for item in items:
                key = hash_text(item.url)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(item)
            items = unique
        return [self.capture_url(item, user_id=user_id) for item in items]

    def get_status(self, capture_id: str, *, user_id: str) -> CaptureStatusResponse:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT capture_id, status, stage, stage_detail, url, title, job_id, error
                FROM captures WHERE capture_id = ? AND user_id = ?
                """,
                (capture_id, user_id),
            ).fetchone()
        if not row:
            raise KeyError("Capture not found")
        stage = row["stage"] or row["status"]
        return CaptureStatusResponse(
            capture_id=row["capture_id"],
            status=row["status"],
            stage=stage,
            stage_detail=row["stage_detail"] or "",
            url=row["url"],
            title=row["title"] or "",
            job_id=row["job_id"],
            error=row["error"],
            message=_status_message(row["status"], stage, row["stage_detail"], row["error"]),
        )

    def import_bookmarks(self, payload: BookmarkImportRequest, *, user_id: str) -> dict:
        return self._imports.import_bookmarks(payload, user_id=user_id, async_processing=True)

    def _process_capture_sync(
        self,
        capture_id: str,
        user_id: str,
        payload: CaptureUrlRequest,
    ) -> CaptureStatusResponse:
        try:
            self._run_capture_pipeline(capture_id, user_id, payload)
        except Exception as exc:
            logger.exception("Capture %s failed", capture_id)
            self._update_stage(
                capture_id,
                user_id,
                status="failed",
                stage="failed",
                detail=str(exc),
                error=str(exc),
            )
        return self.get_status(capture_id, user_id=user_id)

    def _process_capture_async(
        self,
        capture_id: str,
        user_id: str,
        payload: CaptureUrlRequest,
    ) -> None:
        try:
            self._run_capture_pipeline(capture_id, user_id, payload)
        except Exception as exc:
            logger.exception("Async capture %s failed", capture_id)
            self._update_stage(
                capture_id,
                user_id,
                status="failed",
                stage="failed",
                detail=str(exc),
                error=str(exc),
            )

    def _process_youtube_capture(
        self,
        capture_id: str,
        user_id: str,
        payload: CaptureUrlRequest,
    ) -> None:
        self._process_capture_async(capture_id, user_id, payload)

    def _run_capture_pipeline(
        self,
        capture_id: str,
        user_id: str,
        payload: CaptureUrlRequest,
    ) -> None:
        url = payload.url.strip()
        if is_valid_youtube_url(url):
            self._run_youtube_pipeline(capture_id, user_id, payload)
            return

        reflection = payload.reflection or _reflection_from_payload(payload)

        def on_stage(stage: str, detail: str = "") -> None:
            status = "processing"
            if stage in {"queued"}:
                status = "queued"
            if stage in {"completed", "indexed"}:
                status = "completed"
            if stage == "failed":
                status = "failed"
            if stage == "embedding":
                status = "embedding"
            self._update_stage(
                capture_id, user_id, status=status, stage=stage, detail=detail or stage
            )

        result = self._connector_ingest.ingest_url(
            url,
            user_id=user_id,
            reflection=reflection,
            selected_text=payload.selected_text or "",
            stage_callback=on_stage,
            ref_extra={"title": payload.title} if payload.title else None,
        )
        if result.success:
            self._update_stage(
                capture_id,
                user_id,
                status="completed",
                stage="completed",
                detail=f"{result.chunk_count or 0} chunks indexed",
            )
        else:
            self._update_stage(
                capture_id,
                user_id,
                status="failed",
                stage="failed",
                detail=result.error or "failed",
                error=result.error,
            )

    def _run_youtube_pipeline(
        self,
        capture_id: str,
        user_id: str,
        payload: CaptureUrlRequest,
    ) -> None:
        reflection = payload.reflection or _reflection_from_payload(payload)
        playback = None
        notes = ""
        playlist_id = None
        if payload.observed:
            playback = payload.observed.progress_sec
            notes = (payload.observed.description or "")[:500] if False else ""
            playlist_id = (payload.observed.extra or {}).get("playlist_id")

        def on_stage(stage: str, detail: str = "") -> None:
            status = stage if stage in {"queued", "failed", "completed", "retry"} else "processing"
            if stage in {"embedding", "indexed", "completed"}:
                status = "embedding" if stage == "embedding" else (
                    "completed" if stage in {"indexed", "completed"} else status
                )
            if stage == "failed":
                status = "failed"
            if stage == "retry":
                status = "retry"
            self._update_stage(
                capture_id,
                user_id,
                status=status if status != "processing" else stage,
                stage=stage,
                detail=detail or stage,
            )

        result = self._ingest.ingest_single_url(
            payload.url.strip(),
            user_id=user_id,
            reflection=reflection,
            stage_callback=on_stage,
            run_id=capture_id,
            capture_id=capture_id,
            playback_position_sec=playback,
            user_notes=payload.goal or notes,
            playlist_id=playlist_id,
        )
        if result.success:
            detail = "Already in Memory" if result.skipped else "Indexed in Memory"
            self._update_stage(
                capture_id,
                user_id,
                status="completed",
                stage="completed",
                detail=detail,
                title=result.title or payload.title,
            )
        else:
            self._update_stage(
                capture_id,
                user_id,
                status="failed",
                stage="failed",
                detail=result.error or "Ingest failed",
                error=result.error,
            )

    def _update_stage(
        self,
        capture_id: str,
        user_id: str,
        *,
        status: str,
        stage: str,
        detail: str = "",
        error: str | None = None,
        title: str | None = None,
    ) -> None:
        now = _utc_now()
        with get_connection(self._settings) as conn:
            if title is not None:
                conn.execute(
                    """
                    UPDATE captures
                    SET status = ?, stage = ?, stage_detail = ?, error = ?, title = ?, updated_at = ?
                    WHERE capture_id = ? AND user_id = ?
                    """,
                    (status, stage, detail, error, title, now, capture_id, user_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE captures
                    SET status = ?, stage = ?, stage_detail = ?, error = ?, updated_at = ?
                    WHERE capture_id = ? AND user_id = ?
                    """,
                    (status, stage, detail, error, now, capture_id, user_id),
                )

    def _rewrite_payload(self, capture_id: str, user_id: str, payload: CaptureUrlRequest) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                "UPDATE captures SET payload_json = ?, updated_at = ? WHERE capture_id = ? AND user_id = ?",
                (payload.model_dump_json(), _utc_now(), capture_id, user_id),
            )


def _reflection_from_payload(payload: CaptureUrlRequest) -> ReflectionInput | None:
    if payload.reflection:
        return payload.reflection
    if not payload.goal and not payload.save_reason:
        return None
    reason = SaveReason.OTHER
    if payload.save_reason:
        try:
            reason = SaveReason(payload.save_reason)
        except ValueError:
            reason = SaveReason.OTHER
    return ReflectionInput(save_reason=reason, goal=payload.goal or "")


def _status_message(status: str, stage: str, detail: str | None, error: str | None) -> str:
    if status == "failed" or stage == "failed":
        return error or detail or "Failed"
    if detail:
        return detail
    return stage or status


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

"""Import manager and connector health APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.capture import BookmarkImportRequest
from app.models.user import UserPublic
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.import_manager import ImportManager
from app.services.notion_import_service import NotionImportService
from app.services.readwise_import_service import ReadwiseImportService

router = APIRouter(tags=["imports"])


def _manager(settings: Settings = Depends(get_settings)) -> ImportManager:
    return ImportManager(settings)


@router.get("/connectors/health")
def connectors_health(
    user: UserPublic = Depends(get_current_user),
    manager: ImportManager = Depends(_manager),
) -> dict:
    return {"connectors": manager.connector_health()}


@router.get("/imports")
def list_imports(
    limit: int = Query(50, ge=1, le=200),
    user: UserPublic = Depends(get_current_user),
    manager: ImportManager = Depends(_manager),
) -> dict:
    return {"imports": manager.list_imports(user_id=user.user_id, limit=limit)}


@router.get("/imports/{import_id}")
def get_import(
    import_id: str,
    item_limit: int = Query(200, ge=1, le=2000),
    user: UserPublic = Depends(get_current_user),
    manager: ImportManager = Depends(_manager),
) -> dict:
    try:
        return manager.get_import(import_id, user_id=user.user_id, item_limit=item_limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Import not found.") from exc


@router.post("/imports/{import_id}/start")
def start_import(
    import_id: str,
    user: UserPublic = Depends(get_current_user),
    manager: ImportManager = Depends(_manager),
) -> dict:
    try:
        return manager.start_import_async(import_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Import not found.") from exc


@router.post("/imports/{import_id}/cancel")
def cancel_import(
    import_id: str,
    user: UserPublic = Depends(get_current_user),
    manager: ImportManager = Depends(_manager),
) -> dict:
    try:
        return manager.cancel_import(import_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Import not found.") from exc


@router.post("/capture/bookmarks/preview")
def preview_bookmarks(
    body: BookmarkImportRequest,
    user: UserPublic = Depends(get_current_user),
    manager: ImportManager = Depends(_manager),
) -> dict:
    return manager.preview_bookmarks(body, user_id=user.user_id)


@router.post("/imports/readwise/csv/preview")
async def preview_readwise_csv(
    file: UploadFile = File(...),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Readwise CSV too large (max 20MB).")
    try:
        return ReadwiseImportService(settings).preview_csv(data)
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/imports/readwise/csv")
async def import_readwise_csv(
    file: UploadFile = File(...),
    force_refresh: bool = Form(False),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Readwise CSV too large (max 20MB).")
    try:
        return ReadwiseImportService(settings).ingest_csv(
            data,
            user_id=user.user_id,
            force_refresh=force_refresh,
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/imports/notion/zip/preview")
async def preview_notion_zip(
    file: UploadFile = File(...),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Notion ZIP too large (max 50MB compressed).")
    try:
        return NotionImportService(settings).preview_zip(data)
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/imports/notion/zip")
async def import_notion_zip(
    file: UploadFile = File(...),
    force_refresh: bool = Form(False),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Notion ZIP too large (max 50MB compressed).")
    try:
        return NotionImportService(settings).ingest_zip(
            data,
            user_id=user.user_id,
            force_refresh=force_refresh,
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/capture/pdf")
async def capture_pdf(
    file: UploadFile = File(...),
    title: str = Form(""),
    async_processing: bool = Form(False),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty PDF upload.")
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 50MB).")
    content_type = (file.content_type or "").lower()
    filename = title or file.filename or "document.pdf"
    looks_pdf = data[:5] == b"%PDF-" or filename.lower().endswith(".pdf")
    if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
        if not looks_pdf:
            raise HTTPException(status_code=400, detail="Upload must be a PDF.")
    if not looks_pdf:
        raise HTTPException(status_code=400, detail="Upload must be a PDF.")
    service = ConnectorIngestService(settings)
    if async_processing:
        # Synchronous ingest for reliability in V1-4; flag reserved for future job queue.
        pass
    result = service.ingest_pdf_bytes(
        data, user_id=user.user_id, filename=filename
    )
    return {
        "success": result.success,
        "skipped": result.skipped,
        "external_id": result.video_id,
        "title": result.title,
        "chunk_count": result.chunk_count,
        "error": result.error,
        "stages": [s.model_dump() for s in result.stages],
        "source_type": "pdf",
        "connector_id": "pdf.v1",
    }

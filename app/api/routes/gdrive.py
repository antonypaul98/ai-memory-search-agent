"""Authenticated Google Drive read-only connector APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.user import UserPublic
from app.services.gdrive_import_service import GoogleDriveImportService

router = APIRouter(prefix="/gdrive", tags=["google-drive"])


class GoogleDriveImportRequest(BaseModel):
    force_refresh: bool = False


def _service(settings: Settings = Depends(get_settings)) -> GoogleDriveImportService:
    try:
        return GoogleDriveImportService(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Connector OAuth storage is not configured.") from exc


@router.get("/files")
def preview_files(
    limit: int = Query(default=25, ge=1, le=100),
    page_token: str = "",
    user: UserPublic = Depends(get_current_user),
    service: GoogleDriveImportService = Depends(_service),
) -> dict:
    try:
        return service.list_files(user_id=user.user_id, limit=limit, page_token=page_token)
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/files/{file_id}/import")
def import_file(
    file_id: str,
    payload: GoogleDriveImportRequest,
    user: UserPublic = Depends(get_current_user),
    service: GoogleDriveImportService = Depends(_service),
) -> dict:
    try:
        return service.import_file(
            user_id=user.user_id,
            file_id=file_id,
            force_refresh=payload.force_refresh,
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

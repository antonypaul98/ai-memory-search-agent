"""Browser extension capture routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.models.capture import (
    BookmarkImportRequest,
    CaptureBatchRequest,
    CaptureStatusResponse,
    CaptureUrlRequest,
)
from app.models.user import UserPublic
from app.services.capture_service import CaptureService

router = APIRouter(prefix="/capture", tags=["capture"])


@router.post("/url", response_model=CaptureStatusResponse)
def capture_url(
    body: CaptureUrlRequest,
    user: UserPublic = Depends(get_current_user),
) -> CaptureStatusResponse:
    service = CaptureService()
    return service.capture_url(body, user_id=user.user_id)


@router.post("/batch", response_model=list[CaptureStatusResponse])
def capture_batch(
    body: CaptureBatchRequest,
    user: UserPublic = Depends(get_current_user),
) -> list[CaptureStatusResponse]:
    service = CaptureService()
    return service.capture_batch(body, user_id=user.user_id)


@router.get("/status/{capture_id}", response_model=CaptureStatusResponse)
def capture_status(
    capture_id: str,
    user: UserPublic = Depends(get_current_user),
) -> CaptureStatusResponse:
    service = CaptureService()
    try:
        return service.get_status(capture_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Capture not found.") from exc


@router.post("/retry/{capture_id}", response_model=CaptureStatusResponse)
def retry_capture(
    capture_id: str,
    user: UserPublic = Depends(get_current_user),
) -> CaptureStatusResponse:
    service = CaptureService()
    try:
        return service.retry_capture(capture_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Capture not found.") from exc


@router.post("/bookmarks/import")
def import_bookmarks(
    body: BookmarkImportRequest,
    user: UserPublic = Depends(get_current_user),
) -> dict:
    service = CaptureService()
    return service.import_bookmarks(body, user_id=user.user_id)

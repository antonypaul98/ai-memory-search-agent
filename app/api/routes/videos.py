"""
Video ingest and management routes.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_ingest_service
from app.models.user import UserPublic
from app.models.video import IngestRequest, IngestResponse
from app.services.ingest_service import IngestService, MAX_BATCH_SIZE

router = APIRouter(prefix="/videos", tags=["videos"])


@router.post("/ingest", response_model=IngestResponse)
def ingest_videos(
    body: IngestRequest,
    service: IngestService = Depends(get_ingest_service),
    user: UserPublic = Depends(get_current_user),
) -> IngestResponse:
    """
    Batch-ingest YouTube URLs with bounded async concurrency.

    Each URL is processed independently; failures do not stop the batch.
    """
    if len(body.urls) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch limit is {MAX_BATCH_SIZE} URLs.",
        )

    try:
        return service.ingest_batch(
            body.urls,
            reflection=body.reflection,
            force_refresh=body.force_refresh,
            user_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

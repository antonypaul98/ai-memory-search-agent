"""YouTube Memory Agent routes — reference connector APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.db.youtube_memory_store_factory import get_youtube_memory_store
from app.models.user import UserPublic
from app.models.youtube_memory import (
    RelatedMemoriesResponse,
    YouTubeDiagnostics,
    YouTubeMemoryDetail,
)
from app.services.ingest_service import IngestService
from app.services.sources import get_youtube_connector
from app.services.youtube_related_service import YouTubeRelatedService

router = APIRouter(prefix="/youtube", tags=["youtube"])


def _store(settings: Settings = Depends(get_settings)) -> Any:
    return get_youtube_memory_store(settings)


@router.get("/memories/{video_id}", response_model=YouTubeMemoryDetail)
def get_youtube_memory(
    video_id: str,
    user: UserPublic = Depends(get_current_user),
    store: Any = Depends(_store),
) -> YouTubeMemoryDetail:
    memory = store.get(video_id, user_id=user.user_id)
    if not memory:
        raise HTTPException(status_code=404, detail="YouTube memory not found.")
    return YouTubeMemoryDetail(**memory.model_dump(), related_count=0, pipeline_stages=[])


@router.get("/memories/{video_id}/related", response_model=RelatedMemoriesResponse)
def related_youtube_memories(
    video_id: str,
    user: UserPublic = Depends(get_current_user),
) -> RelatedMemoriesResponse:
    return YouTubeRelatedService().related(video_id, user_id=user.user_id)


@router.get("/diagnostics", response_model=YouTubeDiagnostics)
def youtube_diagnostics(
    user: UserPublic = Depends(get_current_user),
    store: Any = Depends(_store),
) -> YouTubeDiagnostics:
    diag = store.diagnostics(user_id=user.user_id)
    health = get_youtube_connector().health()
    diag.healthy = health.healthy
    return diag


@router.post("/retry-queue/process")
def process_retry_queue(
    user: UserPublic = Depends(get_current_user),
    store: Any = Depends(_store),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Process due connector retries for the current user (idempotent re-ingest)."""
    due = store.claim_due_retries(user_id=user.user_id, limit=10)
    ingest = IngestService(settings=settings)
    processed = 0
    succeeded = 0
    for row in due:
        processed += 1
        result = ingest.ingest_single_url(
            row["url"],
            user_id=user.user_id,
            force_refresh=True,
        )
        if result.success:
            succeeded += 1
            store.complete_retry(user_id=user.user_id, retry_id=int(row["id"]))
        else:
            store.enqueue_retry(
                user_id=user.user_id,
                url=row["url"],
                external_id=row["external_id"],
                payload={},
                error=result.error or "retry failed",
                attempt_count=int(row["attempt_count"]),
            )
    return {"processed": processed, "succeeded": succeeded}

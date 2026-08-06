"""Playlist ingestion routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db.job_store import JobStore
from app.models.job import BackgroundJob, PlaylistIngestRequest, PlaylistPreviewResponse
from app.models.user import UserPublic
from app.services.playlist_service import PlaylistResolver

router = APIRouter(prefix="/playlists", tags=["playlists"])


def _preview_or_400(playlist_url: str):
    try:
        return PlaylistResolver().preview(playlist_url)
    except AppError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/preview", response_model=PlaylistPreviewResponse)
def preview_playlist(
    body: PlaylistIngestRequest,
    user: UserPublic = Depends(get_current_user),
) -> PlaylistPreviewResponse:
    data = _preview_or_400(body.playlist_url)
    return PlaylistPreviewResponse(
        playlist_id=data.playlist_id,
        title=data.title,
        video_count=len(data.entries),
        sample_titles=[e.title for e in data.entries[:5] if e.title],
    )


@router.post("/ingest", response_model=BackgroundJob)
def ingest_playlist(
    body: PlaylistIngestRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> BackgroundJob:
    data = _preview_or_400(body.playlist_url)
    if not data.entries:
        raise HTTPException(
            status_code=400,
            detail="Playlist is empty. Nothing to import.",
        )
    max_videos = max(1, int(settings.playlist_max_videos))
    if len(data.entries) > max_videos:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Playlist has {len(data.entries)} videos; V1 import limit is "
                f"{max_videos}. Split the playlist or raise PLAYLIST_MAX_VIDEOS."
            ),
        )
    store = JobStore()
    try:
        return store.create_playlist_job(
            user_id=user.user_id,
            playlist_id=data.playlist_id,
            playlist_title=data.title,
            entries=data.entries,
            reflection=body.reflection,
            force_refresh=body.force_refresh,
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

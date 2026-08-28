"""Podcast RSS import APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.user import UserPublic
from app.services.podcast_import_service import PodcastImportService

router = APIRouter(tags=["imports", "podcasts"])


class PodcastRSSRequest(BaseModel):
    feed_url: str = Field(min_length=8, max_length=2048)
    limit: int = Field(default=25, ge=1, le=100)
    force_refresh: bool = False


@router.post("/imports/podcast/rss/preview")
def preview_podcast_feed(
    body: PodcastRSSRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return PodcastImportService(settings).preview(body.feed_url, limit=body.limit)
    except (AppError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/imports/podcast/rss")
def import_podcast_feed(
    body: PodcastRSSRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return PodcastImportService(settings).ingest(
            body.feed_url,
            user_id=user.user_id,
            limit=body.limit,
            force_refresh=body.force_refresh,
        )
    except (AppError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

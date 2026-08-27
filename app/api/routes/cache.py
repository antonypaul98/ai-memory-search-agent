"""Tenant-scoped semantic cache operations for Phase 2 Memory Intelligence."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings
from app.models.user import UserPublic
from app.services.semantic_cache import SemanticCache

router = APIRouter(prefix="/cache", tags=["cache"])


@router.get("/semantic/stats")
def semantic_cache_stats(
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    """Return cache health for the current tenant only."""
    return SemanticCache(settings).stats(user_id=user.user_id)


@router.delete("/semantic")
def invalidate_semantic_cache(
    query_type: str | None = Query(default=None, min_length=1, max_length=64),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    """Clear the current tenant's semantic cache, optionally for one query type."""
    removed = SemanticCache(settings).invalidate(user_id=user.user_id, query_type=query_type)
    return {
        "removed": removed,
        "query_type": query_type,
        "user_id": user.user_id,
    }

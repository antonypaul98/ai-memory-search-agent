"""Usage tracking and recommendation routes."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.api.dependencies import get_recommendation_service
from app.db.video_registry import VideoRegistry, get_video_registry
from app.models.reflection import FeedbackRequest, RecommendationItem, UsageStats
from app.models.user import UserPublic
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/videos", tags=["videos"])


def _registry() -> VideoRegistry:
    return get_video_registry()


@router.get("/recommendations", response_model=list[RecommendationItem])
def list_recommendations(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=3, ge=1, le=10),
    service: RecommendationService = Depends(get_recommendation_service),
) -> list[RecommendationItem]:
    """Return preference-aware recommendations for a query."""
    return service.recommend_for_query(q, limit=limit)


@router.post("/{video_id}/view", response_model=UsageStats)
def record_view(
    video_id: str,
    user: UserPublic = Depends(get_current_user),
    registry: VideoRegistry = Depends(_registry),
) -> UsageStats:
    """Increment view count when a user opens a memory."""
    if not registry.get_video(video_id, user_id=user.user_id):
        raise HTTPException(status_code=404, detail="Video not found.")
    return registry.record_view(video_id, user_id=user.user_id)


@router.post("/{video_id}/feedback", response_model=UsageStats)
def record_feedback(
    video_id: str,
    body: FeedbackRequest,
    user: UserPublic = Depends(get_current_user),
    registry: VideoRegistry = Depends(_registry),
) -> UsageStats:
    """Record helpful / not helpful feedback."""
    if not registry.get_video(video_id, user_id=user.user_id):
        raise HTTPException(status_code=404, detail="Video not found.")
    return registry.record_feedback(video_id, helpful=body.helpful, user_id=user.user_id)

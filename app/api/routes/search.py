"""
Semantic search routes.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.api.dependencies import get_search_service
from app.models.user import UserPublic
from app.models.video import SearchFilters, SearchResponse
from app.services.search_service import SearchService

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search_memories(
    q: str = Query(..., description="Search query (keywords or natural language)."),
    limit: int = Query(5, ge=1, le=20, description="Maximum videos to return."),
    debug: bool = Query(False, description="Include debug metrics when app debug mode is enabled."),
    channel: str | None = Query(None, description="Filter by channel name substring."),
    date_from: str | None = Query(None, description="Published on/after (YYYY-MM-DD)."),
    date_to: str | None = Query(None, description="Published on/before (YYYY-MM-DD)."),
    transcript_available: bool | None = Query(None),
    duration_min: float | None = Query(None, ge=0),
    duration_max: float | None = Query(None, ge=0),
    language: str | None = Query(None),
    min_confidence: float | None = Query(None, ge=0, le=1),
    tags: str | None = Query(None, description="Comma-separated tags."),
    service: SearchService = Depends(get_search_service),
    user: UserPublic = Depends(get_current_user),
) -> SearchResponse:
    """Hybrid semantic search over saved memories (YouTube transcript chunks + metadata)."""
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    filters = SearchFilters(
        channel=channel,
        date_from=date_from,
        date_to=date_to,
        transcript_available=transcript_available,
        duration_min=duration_min,
        duration_max=duration_max,
        language=language,
        min_confidence=min_confidence,
        tags=[t.strip() for t in (tags or "").split(",") if t.strip()],
    )
    return service.search(
        query=query,
        limit=limit,
        debug=debug,
        user_id=user.user_id,
        filters=filters,
    )

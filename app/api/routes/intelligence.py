"""Memory Intelligence Layer API routes (V1-3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.models.intelligence import (
    ConceptCapsule,
    ConceptCapsuleListResponse,
    CreatorListResponse,
    CreatorProfile,
    DuplicateKnowledgeResponse,
    InsightsDashboard,
    LearningGraphResponse,
    LearningRoadmap,
    NaturalRetrieveResponse,
    TimelineMode,
    TimelineResponse,
    TopicListResponse,
    TopicProfile,
)
from app.models.user import UserPublic
from app.models.video import SearchFilters
from app.services.memory_intelligence_service import MemoryIntelligenceService

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def _intel(settings: Settings = Depends(get_settings)) -> MemoryIntelligenceService:
    return MemoryIntelligenceService(settings=settings)


@router.get("/retrieve", response_model=NaturalRetrieveResponse)
def natural_retrieve(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(5, ge=1, le=20),
    channel: str | None = Query(None),
    language: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    save_reason: str | None = Query(
        None,
        description="Filter by a case-insensitive substring of the current user's save reason.",
    ),
    min_confidence: float | None = Query(None, ge=0, le=1),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> NaturalRetrieveResponse:
    """Natural memory retrieval with full explainability on every hit."""
    filters = SearchFilters(
        channel=channel,
        language=language,
        date_from=date_from,
        date_to=date_to,
        save_reason=save_reason.strip() if save_reason and save_reason.strip() else None,
        min_confidence=min_confidence,
    )
    return service.retrieve(q.strip(), user_id=user.user_id, limit=limit, filters=filters)


@router.get("/topics", response_model=TopicListResponse)
def list_topics(
    limit: int = Query(50, ge=1, le=200),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> TopicListResponse:
    return service.list_topics(user_id=user.user_id, limit=limit)


@router.get("/topics/{topic_id}", response_model=TopicProfile)
def get_topic(
    topic_id: str,
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> TopicProfile:
    topic = service.get_topic(topic_id, user_id=user.user_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return topic


@router.get("/timeline", response_model=TimelineResponse)
def memory_timeline(
    mode: TimelineMode = Query(TimelineMode.RECENTLY_SAVED),
    topic: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> TimelineResponse:
    return service.timeline(user_id=user.user_id, mode=mode, topic=topic, limit=limit)


@router.get("/learning-graph", response_model=LearningGraphResponse)
def learning_graph(
    video_id: str | None = Query(None),
    topic: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> LearningGraphResponse:
    return service.learning_graph(
        user_id=user.user_id, video_id=video_id, topic=topic, limit=limit
    )


@router.get("/roadmap", response_model=LearningRoadmap)
def learning_roadmap(
    topic: str = Query(..., min_length=1, max_length=200),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> LearningRoadmap:
    return service.roadmap(topic, user_id=user.user_id)


@router.get("/capsules", response_model=ConceptCapsuleListResponse)
def list_concept_capsules(
    limit: int = Query(50, ge=1, le=200),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> ConceptCapsuleListResponse:
    return service.list_capsules(user_id=user.user_id, limit=limit)


@router.get("/capsules/{capsule_id}", response_model=ConceptCapsule)
def get_concept_capsule(
    capsule_id: str,
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> ConceptCapsule:
    capsule = service.get_capsule(capsule_id, user_id=user.user_id)
    if not capsule:
        raise HTTPException(status_code=404, detail="Concept capsule not found.")
    return capsule


@router.get("/duplicates", response_model=DuplicateKnowledgeResponse)
def duplicate_knowledge(
    limit: int = Query(40, ge=1, le=100),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> DuplicateKnowledgeResponse:
    return service.duplicate_knowledge(user_id=user.user_id, limit=limit)


@router.get("/creators", response_model=CreatorListResponse)
def list_creators(
    limit: int = Query(50, ge=1, le=200),
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> CreatorListResponse:
    return service.list_creators(user_id=user.user_id, limit=limit)


@router.get("/creators/{creator_id}", response_model=CreatorProfile)
def get_creator(
    creator_id: str,
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> CreatorProfile:
    creator = service.get_creator(creator_id, user_id=user.user_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found.")
    return creator


@router.get("/insights", response_model=InsightsDashboard)
def insights_dashboard(
    user: UserPublic = Depends(get_current_user),
    service: MemoryIntelligenceService = Depends(_intel),
) -> InsightsDashboard:
    return service.insights(user_id=user.user_id)

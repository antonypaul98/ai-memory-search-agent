"""Authenticated Home Agent physical-memory query routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.models.user import UserPublic
from app.services.home_agent.authenticated_query import AuthenticatedHomeAgentQuery
from app.services.home_agent.query_service import HomeAgentQueryService

router = APIRouter(prefix="/home-agent", tags=["home-agent"])


class _StrictRequest(BaseModel):
    class Config:
        extra = "forbid"


class WhereIsRequest(_StrictRequest):
    object_name: str = Field(min_length=1, max_length=200)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class HistoryRequest(_StrictRequest):
    object_name: str = Field(min_length=1, max_length=200)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=100)


class WhereIsResponse(BaseModel):
    found: bool
    text: str | None = None
    object_name: str | None = None
    location: str | None = None
    observed_at: str | None = None
    confidence: float | None = None
    source_id: str | None = None
    evidence_id: str | None = None


class SightingResponse(BaseModel):
    object_name: str
    location: str
    observed_at: str
    confidence: float
    source_id: str
    evidence_id: str


class HistoryResponse(BaseModel):
    sightings: list[SightingResponse]


@router.post("/where-is", response_model=WhereIsResponse)
def where_is(
    body: WhereIsRequest,
    service: HomeAgentQueryService = Depends(get_home_agent_query_service),
    user: UserPublic = Depends(get_current_user),
) -> WhereIsResponse:
    """Resolve an object's latest location for the authenticated user only."""
    query = AuthenticatedHomeAgentQuery(service=service, user=user)
    answer = query.where_is(
        object_name=body.object_name,
        min_confidence=body.min_confidence,
    )
    if answer is None:
        return WhereIsResponse(found=False)
    return WhereIsResponse(
        found=True,
        text=answer.text,
        object_name=answer.object_name,
        location=answer.location,
        observed_at=answer.observed_at,
        confidence=answer.confidence,
        source_id=answer.source_id,
        evidence_id=answer.evidence_id,
    )


@router.post("/history", response_model=HistoryResponse)
def history(
    body: HistoryRequest,
    service: HomeAgentQueryService = Depends(get_home_agent_query_service),
    user: UserPublic = Depends(get_current_user),
) -> HistoryResponse:
    """Return deterministic sighting history for the authenticated user only."""
    query = AuthenticatedHomeAgentQuery(service=service, user=user)
    sightings = query.history(
        object_name=body.object_name,
        min_confidence=body.min_confidence,
        limit=body.limit,
    )
    return HistoryResponse(
        sightings=[
            SightingResponse(
                object_name=item.object_name,
                location=item.location,
                observed_at=item.observed_at.isoformat(),
                confidence=item.confidence,
                source_id=item.source_id,
                evidence_id=item.evidence_id,
            )
            for item in sightings
        ]
    )

"""Authenticated natural-language HTTP boundary for Home Agent physical memory."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.models.user import UserPublic
from app.services.home_agent.authenticated_query import AuthenticatedHomeAgentQuery
from app.services.home_agent.natural_language_query import execute_home_query
from app.services.home_agent.query_service import BeforeLocationAnswer, HomeAgentQueryService, WhereAnswer

router = APIRouter(prefix="/home-agent", tags=["home-agent"])


class NaturalLanguageQueryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=100)

    class Config:
        extra = "forbid"


class NaturalLanguageQueryResponse(BaseModel):
    status: str
    kind: str | None = None
    text: str | None = None
    object_name: str | None = None
    location: str | None = None
    before_location: str | None = None
    observed_at: str | None = None
    moved_at: str | None = None
    confidence: float | None = None
    source_id: str | None = None
    evidence_id: str | None = None
    destination_evidence_id: str | None = None


@router.post("/query", response_model=NaturalLanguageQueryResponse)
def natural_language_query(
    body: NaturalLanguageQueryRequest,
    service: HomeAgentQueryService = Depends(get_home_agent_query_service),
    user: UserPublic = Depends(get_current_user),
) -> NaturalLanguageQueryResponse:
    result = execute_home_query(
        text=body.text,
        query=AuthenticatedHomeAgentQuery(service=service, user=user),
        min_confidence=body.min_confidence,
        limit=body.limit,
    )
    if result.answer is None:
        return NaturalLanguageQueryResponse(status=result.status, kind=result.kind)

    answer = result.answer
    if isinstance(answer, WhereAnswer):
        return NaturalLanguageQueryResponse(
            status=result.status,
            kind=result.kind,
            text=answer.text,
            object_name=answer.object_name,
            location=answer.location,
            observed_at=answer.observed_at,
            confidence=answer.confidence,
            source_id=answer.source_id,
            evidence_id=answer.evidence_id,
        )

    assert isinstance(answer, BeforeLocationAnswer)
    return NaturalLanguageQueryResponse(
        status=result.status,
        kind=result.kind,
        text=answer.text,
        object_name=answer.object_name,
        location=answer.location,
        before_location=answer.before_location,
        moved_at=answer.moved_at,
        confidence=answer.confidence,
        source_id=answer.source_id,
        evidence_id=answer.evidence_id,
        destination_evidence_id=answer.destination_evidence_id,
    )

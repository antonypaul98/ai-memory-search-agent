"""Phase 4 agent runtime API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings
from app.models.agent_runtime import AgentRunRequest, AgentRunResponse
from app.models.capture_triage import CaptureTriageRequest, CaptureTriageResponse
from app.models.consolidation_agent import ConsolidationRequest, ConsolidationResponse
from app.models.gap_agent import GapAnalysisRequest, GapAnalysisResponse
from app.models.ingest_agent import (
    IngestAgentRunRequest,
    IngestAgentRunResponse,
    IngestRule,
    IngestRuleCreate,
)
from app.models.research_agent import ResearchAgentRequest, ResearchAgentResponse
from app.models.review_agent import ReviewQueueRequest, ReviewQueueResponse
from app.models.user import UserPublic
from app.services.agent_runtime import AgentRuntime
from app.services.capture_triage_agent import CaptureTriageAgent
from app.services.consolidation_agent import ConsolidationAgent
from app.services.gap_agent import GapAgent
from app.services.ingest_agent import IngestAgent
from app.services.research_agent import ResearchAgent
from app.services.review_agent import ReviewAgent

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/run", response_model=AgentRunResponse)
def run_agent(
    body: AgentRunRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> AgentRunResponse:
    try:
        return AgentRuntime(settings).run(user_id=user.user_id, request=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/research", response_model=ResearchAgentResponse)
def run_research_agent(
    body: ResearchAgentRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> ResearchAgentResponse:
    """Run bounded, read-only research over the authenticated user's memory."""
    try:
        return ResearchAgent(settings).run(user_id=user.user_id, request=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/queue", response_model=ReviewQueueResponse)
def build_review_queue(
    body: ReviewQueueRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> ReviewQueueResponse:
    """Build a deterministic spaced-review queue for the authenticated user."""
    return ReviewAgent(settings).queue(user_id=user.user_id, request=body)


@router.post("/gaps/analyze", response_model=GapAnalysisResponse)
def analyze_memory_gaps(
    body: GapAnalysisRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> GapAnalysisResponse:
    """Return evidence-backed learning gaps for the authenticated user's goals."""
    return GapAgent(settings).analyze(user_id=user.user_id, request=body)


@router.post("/consolidation/analyze", response_model=ConsolidationResponse)
def analyze_consolidation(
    body: ConsolidationRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> ConsolidationResponse:
    """Return read-only entity-merge and stale-memory maintenance suggestions."""
    return ConsolidationAgent(settings).analyze(user_id=user.user_id, request=body)


@router.post("/capture/triage", response_model=CaptureTriageResponse)
def triage_captures(
    body: CaptureTriageRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> CaptureTriageResponse:
    """Validate/canonicalize/dedupe a capture queue without writing memory."""
    try:
        return CaptureTriageAgent(settings).triage(user_id=user.user_id, request=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ingest/rules", response_model=IngestRule)
def create_ingest_rule(
    body: IngestRuleCreate,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> IngestRule:
    """Create an inert auto-ingest rule; explicit approval is a separate action."""
    return IngestAgent(settings).create_rule(user_id=user.user_id, request=body)


@router.post("/ingest/rules/{rule_id}/approve", response_model=IngestRule)
def approve_ingest_rule(
    rule_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> IngestRule:
    try:
        return IngestAgent(settings).approve_rule(user_id=user.user_id, rule_id=rule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ingest rule not found") from exc


@router.post("/ingest/rules/{rule_id}/run", response_model=IngestAgentRunResponse)
def run_ingest_rule(
    rule_id: str,
    body: IngestAgentRunRequest,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> IngestAgentRunResponse:
    """Run an already-approved rule over trusted connector/schedule candidates."""
    try:
        return IngestAgent(settings).run_rule(
            user_id=user.user_id,
            rule_id=rule_id,
            candidates=body.candidates,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ingest rule not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
def get_agent_run(
    run_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> AgentRunResponse:
    try:
        return AgentRuntime(settings).get_run(user_id=user.user_id, run_id=run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent run not found") from exc


@router.post("/runs/{run_id}/approve", response_model=AgentRunResponse)
def approve_agent_run(
    run_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> AgentRunResponse:
    try:
        return AgentRuntime(settings).approve(user_id=user.user_id, run_id=run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent run not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

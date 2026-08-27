"""Phase 4 agent runtime API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings
from app.models.agent_runtime import AgentRunRequest, AgentRunResponse
from app.models.capture_triage import CaptureTriageRequest, CaptureTriageResponse
from app.models.research_agent import ResearchAgentRequest, ResearchAgentResponse
from app.models.review_agent import ReviewQueueRequest, ReviewQueueResponse
from app.models.user import UserPublic
from app.services.agent_runtime import AgentRuntime
from app.services.capture_triage_agent import CaptureTriageAgent
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

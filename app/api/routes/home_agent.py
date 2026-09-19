"""Authenticated Home Agent physical-memory query and capture-control routes."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_capture_registry, get_home_agent_capture_service, get_home_agent_query_service
from app.api.home_image_dependencies import get_home_agent_authenticated_image_ingest
from app.models.user import UserPublic
from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest
from app.services.home_agent.authenticated_query import AuthenticatedHomeAgentQuery
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import BoundedVisionCaptureService
from app.services.home_agent.observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE
from app.services.home_agent.query_service import HomeAgentQueryService
from app.services.home_agent.vision_adapter import VisionDetection

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

class MovementHistoryRequest(_StrictRequest):
    object_name: str = Field(min_length=1, max_length=200)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=100)

class BeforeLocationRequest(MovementHistoryRequest):
    location: str = Field(min_length=1, max_length=500)

class StartCaptureSessionRequest(_StrictRequest):
    source_id: str = Field(min_length=1, max_length=200)
    ttl_seconds: int = Field(default=300, ge=1, le=900)

class CaptureDetectionRequest(_StrictRequest):
    session_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    object_name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=500)
    observed_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_id: str = Field(min_length=1, max_length=500)

class WhereIsResponse(BaseModel):
    found: bool
    text: str | None = None
    object_name: str | None = None
    location: str | None = None
    observed_at: str | None = None
    confidence: float | None = None
    source_id: str | None = None
    evidence_id: str | None = None
    evidence_frame_id: str | None = None
    evidence_image_sha256: str | None = None
    evidence_detector_id: str | None = None

class SightingResponse(BaseModel):
    object_name: str
    location: str
    observed_at: str
    confidence: float
    source_id: str
    evidence_id: str

class HistoryResponse(BaseModel):
    sightings: list[SightingResponse]

class MovementEventResponse(BaseModel):
    object_name: str
    from_location: str
    to_location: str
    moved_at: str
    confidence: float
    source_id: str
    from_evidence_id: str
    to_evidence_id: str

class MovementHistoryResponse(BaseModel):
    movements: list[MovementEventResponse]

class BeforeLocationResponse(BaseModel):
    found: bool
    text: str | None = None
    object_name: str | None = None
    location: str | None = None
    before_location: str | None = None
    moved_at: str | None = None
    confidence: float | None = None
    source_id: str | None = None
    evidence_id: str | None = None
    destination_evidence_id: str | None = None

class CaptureSessionResponse(BaseModel):
    session_id: str
    source_id: str
    started_at: str
    expires_at: str

class CaptureDetectionResponse(BaseModel):
    stored: bool

class CaptureImageResponse(BaseModel):
    stored: bool
    frame_id: str | None = None
    detection_ms: float | None = None
    ingestion_ms: float | None = None

@router.post("/where-is", response_model=WhereIsResponse)
def where_is(body: WhereIsRequest, service: HomeAgentQueryService = Depends(get_home_agent_query_service), user: UserPublic = Depends(get_current_user)) -> WhereIsResponse:
    answer = AuthenticatedHomeAgentQuery(service=service, user=user).where_is(object_name=body.object_name, min_confidence=body.min_confidence)
    if answer is None:
        return WhereIsResponse(found=False)
    return WhereIsResponse(found=True, text=answer.text, object_name=answer.object_name, location=answer.location, observed_at=answer.observed_at, confidence=answer.confidence, source_id=answer.source_id, evidence_id=answer.evidence_id, evidence_frame_id=answer.evidence_frame_id, evidence_image_sha256=answer.evidence_image_sha256, evidence_detector_id=answer.evidence_detector_id)

@router.get("/evidence/{frame_id}")
def evidence_frame(frame_id: str, service: HomeAgentQueryService = Depends(get_home_agent_query_service), user: UserPublic = Depends(get_current_user)) -> Response:
    image = service.evidence_frame(user_id=user.user_id, frame_id=frame_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Evidence frame not found.")
    return Response(content=image, media_type="application/octet-stream")

@router.post("/history", response_model=HistoryResponse)
def history(body: HistoryRequest, service: HomeAgentQueryService = Depends(get_home_agent_query_service), user: UserPublic = Depends(get_current_user)) -> HistoryResponse:
    sightings = AuthenticatedHomeAgentQuery(service=service, user=user).history(object_name=body.object_name, min_confidence=body.min_confidence, limit=body.limit)
    return HistoryResponse(sightings=[SightingResponse(object_name=item.object_name, location=item.location, observed_at=item.observed_at.isoformat(), confidence=item.confidence, source_id=item.source_id, evidence_id=item.evidence_id) for item in sightings])

@router.post("/movement-history", response_model=MovementHistoryResponse)
def movement_history(body: MovementHistoryRequest, service: HomeAgentQueryService = Depends(get_home_agent_query_service), user: UserPublic = Depends(get_current_user)) -> MovementHistoryResponse:
    movements = AuthenticatedHomeAgentQuery(service=service, user=user).movement_history(object_name=body.object_name, min_confidence=body.min_confidence, limit=body.limit)
    return MovementHistoryResponse(movements=[MovementEventResponse(object_name=item.object_name, from_location=item.from_location, to_location=item.to_location, moved_at=item.moved_at, confidence=item.confidence, source_id=item.source_id, from_evidence_id=item.from_evidence_id, to_evidence_id=item.to_evidence_id) for item in movements])

@router.post("/before-location", response_model=BeforeLocationResponse)
def before_location(body: BeforeLocationRequest, service: HomeAgentQueryService = Depends(get_home_agent_query_service), user: UserPublic = Depends(get_current_user)) -> BeforeLocationResponse:
    answer = AuthenticatedHomeAgentQuery(service=service, user=user).before_location(object_name=body.object_name, location=body.location, min_confidence=body.min_confidence, limit=body.limit)
    if answer is None:
        return BeforeLocationResponse(found=False)
    return BeforeLocationResponse(found=True, text=answer.text, object_name=answer.object_name, location=answer.location, before_location=answer.before_location, moved_at=answer.moved_at, confidence=answer.confidence, source_id=answer.source_id, evidence_id=answer.evidence_id, destination_evidence_id=answer.destination_evidence_id)

@router.post("/capture-sessions", response_model=CaptureSessionResponse)
def start_capture_session(body: StartCaptureSessionRequest, service: BoundedVisionCaptureService = Depends(get_home_agent_capture_service), registry: CaptureSessionRegistry = Depends(get_home_agent_capture_registry), user: UserPublic = Depends(get_current_user)) -> CaptureSessionResponse:
    session = service.start_session(user_id=user.user_id, source_id=body.source_id, ttl=timedelta(seconds=body.ttl_seconds))
    registry.register(session)
    return CaptureSessionResponse(session_id=session.session_id, source_id=session.source_id, started_at=session.started_at.isoformat(), expires_at=session.expires_at.isoformat())

@router.post("/capture-detections", response_model=CaptureDetectionResponse)
def ingest_capture_detection(body: CaptureDetectionRequest, service: BoundedVisionCaptureService = Depends(get_home_agent_capture_service), registry: CaptureSessionRegistry = Depends(get_home_agent_capture_registry), user: UserPublic = Depends(get_current_user)) -> CaptureDetectionResponse:
    now = datetime.now(timezone.utc)
    try:
        session = registry.resolve(session_id=body.session_id, user_id=user.user_id, source_id=body.source_id, now=now)
        consent = ObservationConsent(user_id=user.user_id, source_id=session.source_id, scope=PHYSICAL_OBSERVATION_SCOPE, granted_at=session.started_at, expires_at=session.expires_at)
        stored = service.ingest_detection(user_id=user.user_id, session=session, detection=VisionDetection(object_name=body.object_name, location=body.location, observed_at=body.observed_at, confidence=body.confidence, source_id=body.source_id, evidence_id=body.evidence_id), consent=consent, now=now)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Capture session is missing, mismatched, or expired.") from exc
    return CaptureDetectionResponse(stored=stored)

@router.post("/capture-images", response_model=CaptureImageResponse)
async def ingest_capture_image(request: Request, session_id: str, source_id: str, location: str, observed_at: datetime, service: AuthenticatedHomeImageIngest = Depends(get_home_agent_authenticated_image_ingest), user: UserPublic = Depends(get_current_user)) -> CaptureImageResponse:
    image_bytes = await request.body()
    try:
        result = service.ingest(session_id=session_id, user_id=user.user_id, source_id=source_id, image_bytes=image_bytes, location=location, observed_at=observed_at)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Capture session is missing, mismatched, or expired.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CaptureImageResponse(stored=bool(result.get("stored", True)), frame_id=result.get("frame_id"), detection_ms=result.get("detection_ms"), ingestion_ms=result.get("ingestion_ms"))

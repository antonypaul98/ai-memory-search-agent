"""Universal memory API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore, get_memory_store
from app.models.lifecycle import MemoryMergeRequest
from app.models.trust import TrustMetrics
from app.models.universal_memory import UniversalMemory, UniversalMemoryDetail
from app.models.user import UserPublic
from app.models.video import SourceType
from app.services.event_bus import EventBus
from app.services.memory_lifecycle_service import (
    InvalidLifecycleTransitionError,
    MemoryLifecycleService,
)
from app.services.privacy_service import PrivacyService

router = APIRouter(prefix="/memories", tags=["memories"])


def _store(settings: Settings = Depends(get_settings)) -> MemoryStore:
    return get_memory_store(settings)


def _lifecycle(
    store: MemoryStore = Depends(_store),
    settings: Settings = Depends(get_settings),
) -> MemoryLifecycleService:
    return MemoryLifecycleService(settings=settings, store=store)


def _privacy(settings: Settings = Depends(get_settings)) -> PrivacyService:
    return PrivacyService(settings)


@router.get("", response_model=list[UniversalMemory])
def list_memories(
    limit: int = Query(default=40, ge=1, le=200),
    user: UserPublic = Depends(get_current_user),
    store: MemoryStore = Depends(_store),
) -> list[UniversalMemory]:
    return store.list_recent(user_id=user.user_id, limit=limit)


@router.get("/by-external", response_model=UniversalMemory)
def get_memory_by_external(
    source_type: SourceType = Query(...),
    external_id: str = Query(..., min_length=1),
    user: UserPublic = Depends(get_current_user),
    store: MemoryStore = Depends(_store),
) -> UniversalMemory:
    memory = store.get_by_external(
        user_id=user.user_id,
        source_type=source_type,
        external_id=external_id,
    )
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return memory


@router.get("/{memory_id}", response_model=UniversalMemoryDetail)
def get_memory(
    memory_id: str,
    user: UserPublic = Depends(get_current_user),
    store: MemoryStore = Depends(_store),
) -> UniversalMemoryDetail:
    detail = store.get_detail(memory_id, user_id=user.user_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return detail


@router.get("/{memory_id}/lifecycle", response_model=list)
def get_memory_lifecycle(
    memory_id: str,
    user: UserPublic = Depends(get_current_user),
    store: MemoryStore = Depends(_store),
) -> list:
    if not store.get(memory_id, user_id=user.user_id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return [t.model_dump() for t in store.list_transitions(memory_id)]


@router.get("/{memory_id}/trust", response_model=TrustMetrics)
def get_memory_trust(
    memory_id: str,
    user: UserPublic = Depends(get_current_user),
    store: MemoryStore = Depends(_store),
) -> TrustMetrics:
    memory = store.get(memory_id, user_id=user.user_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found.")
    if not memory.trust:
        raise HTTPException(status_code=404, detail="Trust metrics not computed.")
    return memory.trust


@router.post("/{memory_id}/archive", response_model=UniversalMemory)
def archive_memory(
    memory_id: str,
    user: UserPublic = Depends(get_current_user),
    lifecycle: MemoryLifecycleService = Depends(_lifecycle),
) -> UniversalMemory:
    try:
        return lifecycle.archive(memory_id=memory_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found.") from exc


@router.post("/{memory_id}/revive", response_model=UniversalMemory)
def revive_memory(
    memory_id: str,
    user: UserPublic = Depends(get_current_user),
    lifecycle: MemoryLifecycleService = Depends(_lifecycle),
) -> UniversalMemory:
    try:
        return lifecycle.revive(memory_id=memory_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found.") from exc


@router.post("/{memory_id}/merge", response_model=UniversalMemory)
def merge_memory(
    memory_id: str,
    body: MemoryMergeRequest,
    user: UserPublic = Depends(get_current_user),
    lifecycle: MemoryLifecycleService = Depends(_lifecycle),
) -> UniversalMemory:
    """Mark one trusted memory as merged into another after explicit approval.

    This is intentionally lifecycle-only: the canonical target remains untouched and
    the source transition is auditable/reversible at the data-model level. Tenant
    scoping is enforced by the lifecycle store on both source and target lookups.
    """
    if not body.confirm:
        raise HTTPException(status_code=409, detail="Memory merge requires explicit confirmation.")
    if memory_id == body.into_memory_id:
        raise HTTPException(status_code=400, detail="A memory cannot be merged into itself.")
    try:
        return lifecycle.merge(
            memory_id=memory_id,
            user_id=user.user_id,
            into_memory_id=body.into_memory_id,
            reason=body.reason.strip() or "duplicate_merge",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory or merge target not found.") from exc
    except InvalidLifecycleTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{memory_id}")
def delete_memory(
    request: Request,
    memory_id: str,
    user: UserPublic = Depends(get_current_user),
    privacy: PrivacyService = Depends(_privacy),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    try:
        result = privacy.delete_memory(memory_id=memory_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found.") from exc
    EventBus(settings).emit(
        user_id=user.user_id,
        event_type="memory.deleted",
        aggregate_type="memory",
        aggregate_id=memory_id,
        actor="user",
        request_id=getattr(request.state, "request_id", None),
        payload={"deleted": True},
    )
    return result

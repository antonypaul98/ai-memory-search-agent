"""Background job control routes."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings
from app.config import Settings
from app.core.exceptions import AppError
from app.db.job_store import JobStore
from app.models.job import BackgroundJob, JobDetailResponse
from app.models.user import UserPublic
from app.services.event_bus import EventBus

router = APIRouter(tags=["jobs"])


def _job_http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Job not found.")
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.message)
    return HTTPException(status_code=400, detail=str(exc))


def _emit_job_state_change(
    *,
    settings: Settings,
    request: Request,
    user_id: str,
    job_id: str,
    action: str,
    job: BackgroundJob | None = None,
) -> None:
    """Persist bounded lifecycle metadata without job URLs, titles, or errors."""
    payload: dict[str, object] = {"action": action}
    if job is not None:
        payload.update(
            {
                "status": job.status,
                "paused": job.paused,
                "queued": job.queued,
                "processing": job.processing,
                "completed": job.completed,
                "skipped": job.skipped,
                "failed": job.failed,
                "total_videos": job.total_videos,
            }
        )
    EventBus(settings).emit(
        user_id=user_id,
        event_type="job.state_changed",
        aggregate_type="job",
        aggregate_id=job_id,
        actor="user",
        request_id=getattr(request.state, "request_id", None),
        payload=payload,
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, user: UserPublic = Depends(get_current_user)) -> JobDetailResponse:
    store = JobStore()
    try:
        return store.get_job_detail(job_id, user_id=user.user_id)
    except KeyError as exc:
        raise _job_http(exc) from exc


@router.post("/jobs/{job_id}/pause", response_model=BackgroundJob)
def pause_job(
    request: Request,
    job_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> BackgroundJob:
    store = JobStore(settings)
    try:
        job = store.set_paused(job_id, user_id=user.user_id, paused=True)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc
    _emit_job_state_change(
        settings=settings,
        request=request,
        user_id=user.user_id,
        job_id=job_id,
        action="pause",
        job=job,
    )
    return job


@router.post("/jobs/{job_id}/resume", response_model=BackgroundJob)
def resume_job(
    request: Request,
    job_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> BackgroundJob:
    store = JobStore(settings)
    try:
        job = store.set_paused(job_id, user_id=user.user_id, paused=False)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc
    _emit_job_state_change(
        settings=settings,
        request=request,
        user_id=user.user_id,
        job_id=job_id,
        action="resume",
        job=job,
    )
    return job


@router.post("/jobs/{job_id}/retry-failed", response_model=BackgroundJob)
def retry_failed(
    request: Request,
    job_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> BackgroundJob:
    store = JobStore(settings)
    try:
        job = store.retry_failed(job_id, user_id=user.user_id)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc
    _emit_job_state_change(
        settings=settings,
        request=request,
        user_id=user.user_id,
        job_id=job_id,
        action="retry_failed",
        job=job,
    )
    return job


@router.post("/jobs/{job_id}/cancel", response_model=BackgroundJob)
def cancel_job(
    request: Request,
    job_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> BackgroundJob:
    store = JobStore(settings)
    try:
        job = store.cancel_job(job_id, user_id=user.user_id)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc
    _emit_job_state_change(
        settings=settings,
        request=request,
        user_id=user.user_id,
        job_id=job_id,
        action="cancel",
        job=job,
    )
    return job


@router.delete("/jobs/{job_id}")
def delete_job(
    request: Request,
    job_id: str,
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    store = JobStore(settings)
    try:
        store.delete_job(job_id, user_id=user.user_id)
    except KeyError as exc:
        raise _job_http(exc) from exc
    _emit_job_state_change(
        settings=settings,
        request=request,
        user_id=user.user_id,
        job_id=job_id,
        action="delete",
    )
    return {"deleted": True}

"""Background job control routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.core.exceptions import AppError
from app.db.job_store import JobStore
from app.models.job import BackgroundJob, JobDetailResponse
from app.models.user import UserPublic

router = APIRouter(tags=["jobs"])


def _job_http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Job not found.")
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.message)
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, user: UserPublic = Depends(get_current_user)) -> JobDetailResponse:
    store = JobStore()
    try:
        return store.get_job_detail(job_id, user_id=user.user_id)
    except KeyError as exc:
        raise _job_http(exc) from exc


@router.post("/jobs/{job_id}/pause", response_model=BackgroundJob)
def pause_job(job_id: str, user: UserPublic = Depends(get_current_user)) -> BackgroundJob:
    store = JobStore()
    try:
        return store.set_paused(job_id, user_id=user.user_id, paused=True)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc


@router.post("/jobs/{job_id}/resume", response_model=BackgroundJob)
def resume_job(job_id: str, user: UserPublic = Depends(get_current_user)) -> BackgroundJob:
    store = JobStore()
    try:
        return store.set_paused(job_id, user_id=user.user_id, paused=False)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc


@router.post("/jobs/{job_id}/retry-failed", response_model=BackgroundJob)
def retry_failed(job_id: str, user: UserPublic = Depends(get_current_user)) -> BackgroundJob:
    store = JobStore()
    try:
        return store.retry_failed(job_id, user_id=user.user_id)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc


@router.post("/jobs/{job_id}/cancel", response_model=BackgroundJob)
def cancel_job(job_id: str, user: UserPublic = Depends(get_current_user)) -> BackgroundJob:
    store = JobStore()
    try:
        return store.cancel_job(job_id, user_id=user.user_id)
    except (KeyError, AppError) as exc:
        raise _job_http(exc) from exc


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, user: UserPublic = Depends(get_current_user)) -> dict:
    store = JobStore()
    try:
        store.delete_job(job_id, user_id=user.user_id)
    except KeyError as exc:
        raise _job_http(exc) from exc
    return {"deleted": True}

"""Explicit bearer-authenticated, tenant-scoped object identity consent.

This authorizes *future independent identity verification* for a source.
It never verifies an object, accepts an instance ID, or starts a camera.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.api.dependencies import _get_home_agent_physical_memory_store
from app.config import Settings, get_settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.models.user import UserPublic

router = APIRouter(prefix="/home-agent", tags=["home-agent"])


class _StrictRequest(BaseModel):
    class Config:
        extra = "forbid"


class IdentityConsentGrantRequest(_StrictRequest):
    source_id: str = Field(min_length=1, max_length=200)
    ttl_seconds: int = Field(default=300, ge=1, le=3600)


class IdentityConsentRevokeRequest(_StrictRequest):
    source_id: str = Field(min_length=1, max_length=200)


class IdentityConsentGrantResponse(BaseModel):
    source_id: str
    expires_at: datetime


class IdentityConsentRevokeResponse(BaseModel):
    erased_associations: int


def get_identity_consent_store() -> PostgresHomeImageStore:
    return _get_home_agent_physical_memory_store()


def _require_explicit_bearer(request: Request, settings: Settings) -> None:
    # Cookie-only sessions are excluded to prevent ambient-cookie CSRF grants.
    # get_current_user separately validates the bearer token when auth is on.
    header = request.headers.get("Authorization", "")
    if (not settings.auth_enabled or not header.lower().startswith("bearer ")
            or not header[7:].strip()):
        raise HTTPException(status_code=403, detail="Explicit bearer authentication required.")


@router.post("/identity-consent/grant", response_model=IdentityConsentGrantResponse)
def grant_identity_consent(
    body: IdentityConsentGrantRequest,
    request: Request,
    store: PostgresHomeImageStore = Depends(get_identity_consent_store),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> IdentityConsentGrantResponse:
    _require_explicit_bearer(request, settings)
    expiry = store.grant_instance_identity_consent(
        user_id=user.user_id, source_id=body.source_id, ttl_seconds=body.ttl_seconds,
    )
    return IdentityConsentGrantResponse(source_id=body.source_id, expires_at=expiry)


@router.post("/identity-consent/revoke", response_model=IdentityConsentRevokeResponse)
def revoke_identity_consent(
    body: IdentityConsentRevokeRequest,
    request: Request,
    store: PostgresHomeImageStore = Depends(get_identity_consent_store),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> IdentityConsentRevokeResponse:
    _require_explicit_bearer(request, settings)
    erased = store.revoke_instance_identity_consent(
        user_id=user.user_id, source_id=body.source_id,
    )
    return IdentityConsentRevokeResponse(erased_associations=erased)

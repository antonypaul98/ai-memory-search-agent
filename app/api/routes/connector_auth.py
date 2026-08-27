"""Tenant-scoped connector OAuth credential management APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.models.user import UserPublic
from app.services.oauth_token_vault import OAuthTokenVault

router = APIRouter(tags=["connector-auth"])


def _vault(settings: Settings = Depends(get_settings)) -> OAuthTokenVault:
    try:
        return OAuthTokenVault(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Connector OAuth storage is not configured.") from exc


@router.get("/connectors/{connector_id}/auth")
def connector_auth_status(
    connector_id: str,
    user: UserPublic = Depends(get_current_user),
    vault: OAuthTokenVault = Depends(_vault),
) -> dict:
    record = vault.get(user_id=user.user_id, connector_id=connector_id, audit_use=False)
    if record is None:
        return {"connector_id": connector_id, "connected": False}
    return {
        "connector_id": connector_id,
        "connected": True,
        "scopes": list(record.scopes),
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "expired": record.expired,
    }


@router.delete("/connectors/{connector_id}/auth")
def revoke_connector_auth(
    connector_id: str,
    user: UserPublic = Depends(get_current_user),
    vault: OAuthTokenVault = Depends(_vault),
) -> dict:
    revoked = vault.revoke(user_id=user.user_id, connector_id=connector_id)
    return {"connector_id": connector_id, "connected": False, "revoked": revoked}

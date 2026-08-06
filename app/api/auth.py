"""Authentication dependency and route helpers."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.db.auth_store import AuthStore
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic


def get_auth_store(settings: Settings = Depends(get_settings)) -> AuthStore:
    store = AuthStore(settings)
    store.ensure_local_user()
    return store


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
) -> UserPublic:
    if not settings.auth_enabled:
        return UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Local Demo User")

    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("session_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = store.resolve_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return user


def get_optional_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
) -> UserPublic:
    try:
        return get_current_user(request, settings, store)
    except HTTPException:
        if settings.auth_enabled:
            raise
        return UserPublic(user_id=LOCAL_DEFAULT_USER_ID, display_name="Local Demo User")

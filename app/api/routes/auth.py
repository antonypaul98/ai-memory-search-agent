"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.auth import get_auth_store, get_current_user
from app.config import Settings, get_settings
from app.db.auth_store import AuthStore
from app.models.user import AuthResponse, LoginRequest, RegisterRequest, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


def _extract_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.cookies.get("session_token", "") or ""


def _session_cookie_kwargs(settings: Settings) -> dict:
    """HttpOnly session cookie; Secure outside debug/local demo."""
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": not (settings.debug or settings.local_demo_mode),
        "max_age": int(settings.session_ttl_hours * 3600),
        "path": "/",
    }


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        "session_token",
        path="/",
        samesite="lax",
        secure=not (settings.debug or settings.local_demo_mode),
    )


@router.get("/me", response_model=UserPublic)
def me(user: UserPublic = Depends(get_current_user)) -> UserPublic:
    return user


@router.post("/register", response_model=AuthResponse)
def register(
    body: RegisterRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
) -> AuthResponse:
    if not settings.auth_enabled:
        raise HTTPException(status_code=403, detail="Auth is disabled in local demo mode.")
    try:
        user = store.create_user(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not register user.") from exc
    token = store.create_session(user.user_id)
    response.set_cookie("session_token", token, **_session_cookie_kwargs(settings))
    return AuthResponse(user=user, token=token)


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
) -> AuthResponse:
    if not settings.auth_enabled:
        raise HTTPException(status_code=403, detail="Auth is disabled in local demo mode.")
    user = store.authenticate(email=body.email, password=body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    token = store.create_session(user.user_id)
    response.set_cookie("session_token", token, **_session_cookie_kwargs(settings))
    return AuthResponse(user=user, token=token)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
) -> dict:
    if not settings.auth_enabled:
        _clear_session_cookie(response, settings)
        return {"logged_out": True, "demo_mode": True}
    token = _extract_token(request)
    if token:
        store.revoke_session(token)
    _clear_session_cookie(response, settings)
    return {"logged_out": True}

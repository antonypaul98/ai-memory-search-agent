"""ASGI middleware for per-IP API rate limiting."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.core.rate_limit import get_rate_limiter


_EXEMPT_PREFIXES = (
    "/static/",
    "/manifest.webmanifest",
    "/sw.js",
    "/privacy",
    "/favicon",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        if path == "/" or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Key by client IP only. Including Bearer/cookie prefixes lets attackers
        # rotate forged tokens and reset their sliding window per unique hint.
        client_host = request.client.host if request.client else "unknown"

        limiter = get_rate_limiter()
        is_auth = path.startswith("/api/v1/auth/") and request.method == "POST"
        if is_auth:
            limit = settings.rate_limit_auth_requests
            window = settings.rate_limit_auth_window_sec
            key = f"auth:{client_host}"
        else:
            limit = settings.rate_limit_requests
            window = settings.rate_limit_window_sec
            key = f"api:{client_host}"

        allowed, remaining, retry_after = limiter.allow(key, limit=limit, window_sec=window)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again shortly."},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

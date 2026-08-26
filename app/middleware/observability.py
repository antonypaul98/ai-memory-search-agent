"""Lightweight single-node observability for the production-hardening phase.

Provides request IDs, key=value request completion logs, and in-process counters.
The counters intentionally stay process-local; distributed metrics belong to the
later scale-out phase.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import Counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("app.requests")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_lock = threading.Lock()
_requests_total = 0
_in_flight = 0
_status_codes: Counter[str] = Counter()
_total_duration_ms = 0.0


def _request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def _record_start() -> None:
    global _in_flight
    with _lock:
        _in_flight += 1


def _record_finish(status_code: int, duration_ms: float) -> None:
    global _requests_total, _in_flight, _total_duration_ms
    with _lock:
        _requests_total += 1
        _in_flight = max(0, _in_flight - 1)
        _status_codes[str(status_code)] += 1
        _total_duration_ms += max(0.0, duration_ms)


def metrics_snapshot() -> dict[str, object]:
    """Return a thread-safe snapshot suitable for the local metrics endpoint."""
    with _lock:
        average = _total_duration_ms / _requests_total if _requests_total else 0.0
        return {
            "requests_total": _requests_total,
            "in_flight": _in_flight,
            "status_codes": dict(_status_codes),
            "average_duration_ms": round(average, 2),
        }


def reset_observability_metrics() -> None:
    """Reset process-local counters; used by tests."""
    global _requests_total, _in_flight, _total_duration_ms
    with _lock:
        _requests_total = 0
        _in_flight = 0
        _status_codes.clear()
        _total_duration_ms = 0.0


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach request IDs, log request completion, and collect basic counters."""

    async def dispatch(self, request: Request, call_next):
        request_id = _request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        _record_start()
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            _record_finish(status_code, duration_ms)
            logger.info(
                "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                request_id,
                request.method,
                request.url.path,
                status_code,
                duration_ms,
            )

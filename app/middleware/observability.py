"""Lightweight single-node observability for the production-hardening phase.

Provides request IDs, key=value request completion logs, and in-process counters.
The counters intentionally stay process-local; distributed metrics belong to the
later scale-out phase. Phase 2 also tracks bounded latency samples for search/chat
and aggregate grounded-chat outcomes without storing user questions or answers.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
import uuid
from collections import Counter, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("app.requests")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_TRACKED_LATENCY_PATHS = frozenset({"/api/v1/search", "/api/v1/chat"})
_MAX_LATENCY_SAMPLES = 500
_lock = threading.Lock()
_requests_total = 0
_in_flight = 0
_status_codes: Counter[str] = Counter()
_total_duration_ms = 0.0
_path_durations_ms: dict[str, deque[float]] = {
    path: deque(maxlen=_MAX_LATENCY_SAMPLES) for path in _TRACKED_LATENCY_PATHS
}
_chat_total = 0
_chat_grounded = 0
_chat_clarification = 0


def _request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def _record_start() -> None:
    global _in_flight
    with _lock:
        _in_flight += 1


def _record_finish(status_code: int, duration_ms: float, path: str = "") -> None:
    global _requests_total, _in_flight, _total_duration_ms
    safe_duration = max(0.0, duration_ms)
    with _lock:
        _requests_total += 1
        _in_flight = max(0, _in_flight - 1)
        _status_codes[str(status_code)] += 1
        _total_duration_ms += safe_duration
        if path in _TRACKED_LATENCY_PATHS:
            _path_durations_ms[path].append(safe_duration)


def record_chat_outcome(*, grounded: bool, needs_clarification: bool) -> None:
    """Record aggregate chat quality without retaining question/answer content."""
    global _chat_total, _chat_grounded, _chat_clarification
    with _lock:
        _chat_total += 1
        if grounded:
            _chat_grounded += 1
        if needs_clarification:
            _chat_clarification += 1


def _latency_summary(samples: list[float]) -> dict[str, object]:
    if not samples:
        return {"count": 0, "average_ms": 0.0, "p95_ms": 0.0}
    ordered = sorted(samples)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "count": len(ordered),
        "average_ms": round(sum(ordered) / len(ordered), 2),
        "p95_ms": round(ordered[p95_index], 2),
    }


def metrics_snapshot() -> dict[str, object]:
    """Return a thread-safe snapshot suitable for the local metrics endpoint."""
    with _lock:
        average = _total_duration_ms / _requests_total if _requests_total else 0.0
        answered = max(0, _chat_total - _chat_clarification)
        grounded_rate = _chat_grounded / answered if answered else 0.0
        path_metrics = {
            path: _latency_summary(list(_path_durations_ms[path]))
            for path in sorted(_TRACKED_LATENCY_PATHS)
        }
        return {
            "requests_total": _requests_total,
            "in_flight": _in_flight,
            "status_codes": dict(_status_codes),
            "average_duration_ms": round(average, 2),
            "route_latency": path_metrics,
            "chat_quality": {
                "total": _chat_total,
                "answered_total": answered,
                "grounded_total": _chat_grounded,
                "clarification_total": _chat_clarification,
                "grounded_rate": round(grounded_rate, 4),
            },
        }


def reset_observability_metrics() -> None:
    """Reset process-local counters; used by tests."""
    global _requests_total, _in_flight, _total_duration_ms
    global _chat_total, _chat_grounded, _chat_clarification
    with _lock:
        _requests_total = 0
        _in_flight = 0
        _status_codes.clear()
        _total_duration_ms = 0.0
        for samples in _path_durations_ms.values():
            samples.clear()
        _chat_total = 0
        _chat_grounded = 0
        _chat_clarification = 0


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
            _record_finish(status_code, duration_ms, request.url.path)
            logger.info(
                "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                request_id,
                request.method,
                request.url.path,
                status_code,
                duration_ms,
            )

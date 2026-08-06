"""In-process sliding-window rate limiter (V1-8 / P-02)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Thread-safe fixed-window counter with deque timestamps."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def allow(self, key: str, *, limit: int, window_sec: float) -> tuple[bool, int, int]:
        """
        Return (allowed, remaining, retry_after_sec).

        remaining is how many requests left in the window after this call (if allowed)
        or 0 if denied.
        """
        if limit <= 0:
            return True, 0, 0
        now = time.monotonic()
        window = float(window_sec)
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry = max(1, int(window - (now - bucket[0])) + 1)
                return False, 0, retry
            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            return True, remaining, 0


_GLOBAL_LIMITER = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _GLOBAL_LIMITER


def reset_rate_limiter() -> None:
    _GLOBAL_LIMITER.reset()

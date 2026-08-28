"""Work notification transport for background jobs.

The durable source of truth remains ``JobStore``.  This transport only wakes
worker processes when new durable work exists, so a lost notification cannot
lose a job.  Redis support is loaded lazily and carries opaque markers only.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol

from app.config import Settings

logger = logging.getLogger(__name__)


class JobQueueTransport(Protocol):
    def notify(self, count: int = 1) -> None: ...

    def wait(self) -> None: ...


class PollingJobQueueTransport:
    """Single-node/default transport using the existing bounded poll delay."""

    def __init__(self, settings: Settings) -> None:
        self._delay = settings.job_poll_interval_sec

    def notify(self, count: int = 1) -> None:
        return None

    def wait(self) -> None:
        time.sleep(self._delay)


class RedisJobQueueTransport:
    """Redis-backed worker wakeups with no job/user payload in Redis.

    Redis is deliberately not the durable job store. Workers still atomically
    claim rows from ``JobStore`` after waking, preserving deterministic status,
    provenance and retry behavior if a Redis notification is duplicated/lost.
    """

    def __init__(self, settings: Settings) -> None:
        env_name = settings.redis_url_env
        redis_url = os.getenv(env_name, "").strip()
        if not redis_url:
            raise RuntimeError(f"Redis queue backend requires {env_name} to be set")
        try:
            import redis  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised in minimal installs
            raise RuntimeError("Redis queue backend requires the optional 'redis' package") from exc

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._queue = settings.redis_queue_name
        self._timeout = max(1, int(settings.redis_block_timeout_sec))

    def notify(self, count: int = 1) -> None:
        # Opaque marker only: never place URLs, user IDs, credentials or content in Redis.
        for _ in range(max(0, int(count))):
            self._client.lpush(self._queue, "work")

    def wait(self) -> None:
        self._client.brpop(self._queue, timeout=self._timeout)


def get_job_queue_transport(settings: Settings) -> JobQueueTransport:
    if settings.job_queue_backend == "redis":
        return RedisJobQueueTransport(settings)
    return PollingJobQueueTransport(settings)

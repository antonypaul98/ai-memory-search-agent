"""Work notification transport for background jobs.

The durable source of truth remains ``JobStore``. This transport only wakes
worker processes when new durable work exists, so a lost notification cannot
lose a job. Redis support is loaded lazily and carries opaque markers only.
"""

from __future__ import annotations

import logging
import os
import socket
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
    """Redis Stream-backed worker wakeups with no job/user payload in Redis.

    Redis is deliberately not the durable job store. Workers still atomically
    claim rows from ``JobStore`` after waking, preserving deterministic status,
    provenance and retry behavior if a Redis notification is duplicated/lost.

    A consumer group prevents one opaque wake marker from waking every worker.
    Markers are acknowledged as soon as consumed because ``JobStore`` remains
    authoritative: if a worker dies after the wakeup, bounded polling and claim
    lease recovery still make the durable item available to another worker.
    """

    _STREAM_MAXLEN = 10_000

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
        self._stream = settings.redis_queue_name
        self._group = f"{self._stream}:workers"
        self._consumer = f"{socket.gethostname()}:{os.getpid()}"
        self._timeout_ms = max(1, int(settings.redis_block_timeout_sec)) * 1000
        self._ensure_group()

    def _ensure_group(self) -> None:
        try:
            self._client.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except Exception as exc:
            # Redis returns BUSYGROUP when another process created the group first.
            # Only that race is safe to ignore; connectivity/auth/config errors fail closed.
            if "BUSYGROUP" not in str(exc).upper():
                raise

    def notify(self, count: int = 1) -> None:
        # Opaque marker only: never place URLs, user IDs, credentials or content in Redis.
        for _ in range(max(0, int(count))):
            self._client.xadd(
                self._stream,
                {"marker": "work"},
                maxlen=self._STREAM_MAXLEN,
                approximate=True,
            )

    def wait(self) -> None:
        messages = self._client.xreadgroup(
            self._group,
            self._consumer,
            {self._stream: ">"},
            count=1,
            block=self._timeout_ms,
        )
        if not messages:
            return
        for _stream_name, entries in messages:
            for message_id, _fields in entries:
                self._client.xack(self._stream, self._group, message_id)


def get_job_queue_transport(settings: Settings) -> JobQueueTransport:
    if settings.job_queue_backend == "redis":
        return RedisJobQueueTransport(settings)
    return PollingJobQueueTransport(settings)

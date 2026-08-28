from __future__ import annotations

import sys
import types

import pytest

from app.config import Settings
from app.services.job_queue_transport import (
    PollingJobQueueTransport,
    RedisJobQueueTransport,
    get_job_queue_transport,
)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.pushes: list[tuple[str, str]] = []
        self.pops: list[tuple[str, int]] = []

    def lpush(self, key: str, value: str) -> None:
        self.pushes.append((key, value))

    def brpop(self, key: str, timeout: int):
        self.pops.append((key, timeout))
        return (key, "work")


class _FakeRedisFactory:
    client = _FakeRedisClient()
    seen_url = None
    seen_decode = None

    @classmethod
    def from_url(cls, url: str, decode_responses: bool = False):
        cls.seen_url = url
        cls.seen_decode = decode_responses
        return cls.client


def test_default_transport_is_polling() -> None:
    settings = Settings(_env_file=None)
    assert settings.job_queue_backend == "sqlite"
    assert isinstance(get_job_queue_transport(settings), PollingJobQueueTransport)


def test_redis_backend_requires_explicit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    settings = Settings(_env_file=None, job_queue_backend="redis")
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        RedisJobQueueTransport(settings)


def test_redis_transport_uses_opaque_markers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeRedisFactory.client = _FakeRedisClient()
    monkeypatch.setenv("REDIS_URL", "redis://user:secret@example.invalid:6379/0")
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_FakeRedisFactory))
    settings = Settings(
        _env_file=None,
        job_queue_backend="redis",
        redis_queue_name="test:wakeup",
        redis_block_timeout_sec=3,
    )

    transport = RedisJobQueueTransport(settings)
    transport.notify(2)
    transport.wait()

    assert _FakeRedisFactory.seen_decode is True
    assert _FakeRedisFactory.client.pushes == [
        ("test:wakeup", "work"),
        ("test:wakeup", "work"),
    ]
    assert _FakeRedisFactory.client.pops == [("test:wakeup", 3)]
    # Credentials are used only to construct the client, never as queue payload.
    assert all("secret" not in value for _, value in _FakeRedisFactory.client.pushes)


def test_redis_notify_ignores_non_positive_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeRedisFactory.client = _FakeRedisClient()
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_FakeRedisFactory))
    transport = RedisJobQueueTransport(Settings(_env_file=None, job_queue_backend="redis"))

    transport.notify(0)
    transport.notify(-4)

    assert _FakeRedisFactory.client.pushes == []

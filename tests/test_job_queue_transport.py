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
        self.groups: list[tuple[str, str, str, bool]] = []
        self.adds: list[tuple[str, dict[str, str], int, bool]] = []
        self.reads: list[tuple[str, str, dict[str, str], int, int]] = []
        self.acks: list[tuple[str, str, str]] = []
        self.next_read = [("test:wakeup", [("1-0", {"marker": "work"})])]
        self.group_error: Exception | None = None

    def xgroup_create(self, stream: str, group: str, id: str, mkstream: bool) -> None:
        self.groups.append((stream, group, id, mkstream))
        if self.group_error is not None:
            raise self.group_error

    def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        self.adds.append((stream, fields, maxlen, approximate))
        return f"{len(self.adds)}-0"

    def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        *,
        count: int,
        block: int,
    ):
        self.reads.append((group, consumer, streams, count, block))
        return self.next_read

    def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acks.append((stream, group, message_id))
        return 1


class _FakeRedisFactory:
    client = _FakeRedisClient()
    seen_url = None
    seen_decode = None

    @classmethod
    def from_url(cls, url: str, decode_responses: bool = False):
        cls.seen_url = url
        cls.seen_decode = decode_responses
        return cls.client


def _install_fake_redis(monkeypatch: pytest.MonkeyPatch, url: str = "redis://localhost:6379/0") -> None:
    _FakeRedisFactory.client = _FakeRedisClient()
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_FakeRedisFactory))


def test_default_transport_is_polling() -> None:
    settings = Settings(_env_file=None)
    assert settings.job_queue_backend == "sqlite"
    assert isinstance(get_job_queue_transport(settings), PollingJobQueueTransport)


def test_redis_backend_requires_explicit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    settings = Settings(_env_file=None, job_queue_backend="redis")
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        RedisJobQueueTransport(settings)


def test_redis_transport_uses_stream_and_opaque_markers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_redis(monkeypatch, "redis://user:secret@example.invalid:6379/0")
    settings = Settings(
        _env_file=None,
        job_queue_backend="redis",
        redis_queue_name="test:wakeup",
        redis_block_timeout_sec=3,
    )

    transport = RedisJobQueueTransport(settings)
    transport.notify(2)
    transport.wait()

    client = _FakeRedisFactory.client
    assert _FakeRedisFactory.seen_decode is True
    assert client.groups == [("test:wakeup", "test:wakeup:workers", "0", True)]
    assert client.adds == [
        ("test:wakeup", {"marker": "work"}, 10_000, True),
        ("test:wakeup", {"marker": "work"}, 10_000, True),
    ]
    assert len(client.reads) == 1
    group, consumer, streams, count, block = client.reads[0]
    assert group == "test:wakeup:workers"
    assert consumer
    assert streams == {"test:wakeup": ">"}
    assert count == 1
    assert block == 3000
    assert client.acks == [("test:wakeup", "test:wakeup:workers", "1-0")]
    # Credentials are used only to construct the client, never as stream payload.
    assert all("secret" not in value for _, fields, _, _ in client.adds for value in fields.values())


def test_redis_notify_ignores_non_positive_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_redis(monkeypatch)
    transport = RedisJobQueueTransport(Settings(_env_file=None, job_queue_backend="redis"))

    transport.notify(0)
    transport.notify(-4)

    assert _FakeRedisFactory.client.adds == []


def test_redis_wait_without_message_does_not_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_redis(monkeypatch)
    _FakeRedisFactory.client.next_read = []
    transport = RedisJobQueueTransport(Settings(_env_file=None, job_queue_backend="redis"))

    transport.wait()

    assert _FakeRedisFactory.client.acks == []


def test_consumer_group_creation_race_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_redis(monkeypatch)
    _FakeRedisFactory.client.group_error = RuntimeError("BUSYGROUP Consumer Group name already exists")

    RedisJobQueueTransport(Settings(_env_file=None, job_queue_backend="redis"))


def test_consumer_group_connectivity_failure_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_redis(monkeypatch)
    _FakeRedisFactory.client.group_error = RuntimeError("connection refused")

    with pytest.raises(RuntimeError, match="connection refused"):
        RedisJobQueueTransport(Settings(_env_file=None, job_queue_backend="redis"))

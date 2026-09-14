"""Selected review scheduling: no SQLite fallback, real transactions and races."""
from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError, get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.db.video_registry import get_video_registry
from app.services.review_schedule_service import ReviewScheduleService


def test_selected_schedule_missing_dsn_never_opens_sqlite(monkeypatch, tmp_path):
    env_name = "P03_REVIEW_MISSING_DSN"
    monkeypatch.delenv(env_name, raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres review opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    settings = Settings(
        _env_file=None, memory_store_backend="postgres", postgres_dsn_env=env_name,
        sqlite_path=str(tmp_path / "forbidden.db"),
    )
    with pytest.raises(PostgresConfigurationError):
        ReviewScheduleService(settings)
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()


@pytest.fixture
def pg_schedule(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"), jobs_enabled=False,
    )
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres review opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    nonce = uuid4().hex
    owner, other = f"review-owner-{nonce}", f"review-other-{nonce}"
    video_id = nonce[:11]
    registry = get_video_registry(settings)
    for tenant in (owner, other):
        registry.upsert_video(
            user_id=tenant, video_id=video_id, url=f"https://youtu.be/{video_id}",
            title="Review acceptance", channel="fixture",
        )
    service = ReviewScheduleService(settings)
    factory = get_postgres_connection_factory(settings)
    try:
        yield settings, service, factory, owner, other, video_id
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM memory_review_schedule WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM video_registry WHERE user_id IN (%s, %s)", (owner, other))
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_postgres_schedule_persists_exact_tenant_and_rejects_unowned_memory(pg_schedule):
    settings, service, _, owner, other, video_id = pg_schedule
    reviewed = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    out = service.record_result(user_id=owner, video_id=video_id, result="good", reviewed_at=reviewed)
    assert out == {
        "video_id": video_id, "result": "good", "review_count": 1,
        "last_reviewed_at": reviewed.isoformat(),
        "next_review_at": (reviewed + timedelta(days=7)).isoformat(),
    }
    restarted = ReviewScheduleService(settings)
    assert restarted.get(user_id=owner, video_id=video_id)["review_count"] == 1
    assert restarted.get(user_id=other, video_id=video_id) is None
    restarted.record_result(user_id=other, video_id=video_id, result="easy", reviewed_at=reviewed)
    assert service.get(user_id=owner, video_id=video_id)["last_result"] == "good"
    assert service.get(user_id=other, video_id=video_id)["last_result"] == "easy"
    with pytest.raises(KeyError, match="video not found"):
        service.record_result(user_id=owner, video_id="unowned", result="good")
    assert service.get(user_id=owner, video_id="unowned") is None
    with pytest.raises(ValueError, match="review result"):
        service.record_result(user_id=owner, video_id=video_id, result="invalid")
    assert service.get(user_id=owner, video_id=video_id)["review_count"] == 1


def test_concurrent_postgres_reviews_do_not_lose_counts(pg_schedule):
    settings, service, _, owner, other, video_id = pg_schedule
    second = ReviewScheduleService(settings)
    barrier = Barrier(2)

    def review(worker):
        barrier.wait(timeout=5)
        return worker.record_result(user_id=owner, video_id=video_id, result="good")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(review, worker) for worker in (service, second)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(result["review_count"] for result in results) == [1, 2]
    assert service.get(user_id=owner, video_id=video_id)["review_count"] == 2
    assert service.get(user_id=other, video_id=video_id) is None


def test_postgres_review_failure_rolls_back_and_retry_increments_once(pg_schedule, monkeypatch):
    _, service, factory, owner, other, video_id = pg_schedule
    service.record_result(user_id=owner, video_id=video_id, result="good")
    before = service.get(user_id=owner, video_id=video_id)

    @contextmanager
    def fail_before_commit():
        with factory() as conn:
            yield conn
            raise RuntimeError("injected review transaction failure")

    with monkeypatch.context() as patch:
        patch.setattr(service._postgres, "_connection_factory", fail_before_commit)
        with pytest.raises(RuntimeError, match="injected review transaction failure"):
            service.record_result(user_id=owner, video_id=video_id, result="easy")
    assert service.get(user_id=owner, video_id=video_id) == before
    retried = service.record_result(user_id=owner, video_id=video_id, result="easy")
    assert retried["review_count"] == 2
    assert service.get(user_id=other, video_id=video_id) is None

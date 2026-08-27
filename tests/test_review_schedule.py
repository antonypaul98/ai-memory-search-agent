"""Review Agent durable scheduling and policy regression tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.db.schema import migrate
from app.models.agent_runtime import AgentPolicyTier, AgentRunRequest, AgentRunStatus
from app.models.review_agent import ReviewQueueRequest
from app.services.agent_runtime import AgentRuntime
from app.services.review_agent import ReviewAgent
from app.services.review_schedule_service import ReviewScheduleService


def _seed_memory(settings: Settings, *, user_id: str, video_id: str, goal: str = "AI") -> None:
    migrate(settings)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute(
            """
            INSERT INTO video_registry
                (user_id, video_id, url, title, channel, saved_at, last_viewed)
            VALUES (?, ?, ?, ?, 'Demo', ?, NULL)
            """,
            (user_id, video_id, f"https://youtu.be/{video_id}", f"Memory {video_id}", now),
        )
        conn.execute(
            """
            INSERT INTO video_reflection
                (user_id, video_id, save_reason, goal, reflection_note,
                 recommendations_enabled, preferred_creator_only,
                 allow_other_creators, difficulty, preferred_style)
            VALUES (?, ?, 'learn', ?, 'review me', 0, 0, 1, '', '')
            """,
            (user_id, video_id, goal),
        )


def test_record_result_is_tenant_scoped_and_deterministic(test_settings: Settings) -> None:
    _seed_memory(test_settings, user_id="user-a", video_id="shared")
    _seed_memory(test_settings, user_id="user-b", video_id="other")
    reviewed = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    service = ReviewScheduleService(test_settings)
    out = service.record_result(
        user_id="user-a",
        video_id="shared",
        result="good",
        reviewed_at=reviewed,
    )

    assert out["review_count"] == 1
    assert out["next_review_at"] == (reviewed + timedelta(days=7)).isoformat()
    assert service.get(user_id="user-a", video_id="shared") is not None
    assert service.get(user_id="user-b", video_id="shared") is None


def test_record_result_rejects_cross_tenant_memory(test_settings: Settings) -> None:
    _seed_memory(test_settings, user_id="owner", video_id="private")
    service = ReviewScheduleService(test_settings)
    try:
        service.record_result(user_id="other", video_id="private", result="good")
    except KeyError as exc:
        assert "video not found" in str(exc)
    else:
        raise AssertionError("cross-tenant review write must be rejected")


def test_agent_tool_requires_approval_before_review_metadata_write(test_settings: Settings) -> None:
    _seed_memory(test_settings, user_id="user-a", video_id="review-me")
    runtime = AgentRuntime(test_settings)
    request = AgentRunRequest(
        agent_id="review_agent",
        task="Record review result",
        tool="record_review_result",
        arguments={"video_id": "review-me", "result": "easy"},
        policy_tier=AgentPolicyTier.WRITE_MEMORY,
        approved=False,
    )

    pending = runtime.run(user_id="user-a", request=request)
    assert pending.status == AgentRunStatus.AWAITING_APPROVAL
    assert ReviewScheduleService(test_settings).get(user_id="user-a", video_id="review-me") is None

    completed = runtime.approve(user_id="user-a", run_id=pending.run_id)
    assert completed.status == AgentRunStatus.COMPLETED
    assert completed.result is not None
    assert completed.result["result"] == "easy"


def test_review_queue_respects_future_and_due_schedule(test_settings: Settings) -> None:
    _seed_memory(test_settings, user_id="user-a", video_id="scheduled", goal="Systems")
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    schedule = ReviewScheduleService(test_settings)
    schedule.record_result(
        user_id="user-a",
        video_id="scheduled",
        result="good",
        reviewed_at=now,
    )

    before_due = ReviewAgent(test_settings).queue(
        user_id="user-a",
        request=ReviewQueueRequest(stale_days=14),
        now=now + timedelta(days=2),
    )
    assert before_due.items == []

    at_due = ReviewAgent(test_settings).queue(
        user_id="user-a",
        request=ReviewQueueRequest(stale_days=14),
        now=now + timedelta(days=7),
    )
    assert [item.video_id for item in at_due.items] == ["scheduled"]

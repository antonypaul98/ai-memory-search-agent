"""Phase 4d Review Agent regression tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.review_agent import ReviewQueueRequest
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.review_agent import ReviewAgent


def _seed(
    settings: Settings,
    *,
    user_id: str,
    video_id: str,
    goal: str,
    last_viewed: str | None,
    title: str = "Memory",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute(
            """
            INSERT INTO video_registry
                (user_id, video_id, url, title, channel, saved_at, last_viewed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, video_id, f"https://youtu.be/{video_id}", title, "Demo", now, last_viewed),
        )
        conn.execute(
            """
            INSERT INTO video_reflection
                (user_id, video_id, save_reason, goal, reflection_note,
                 recommendations_enabled, preferred_creator_only,
                 allow_other_creators, difficulty, preferred_style)
            VALUES (?, ?, 'learn', ?, 'review this concept', 0, 0, 1, '', '')
            """,
            (user_id, video_id, goal),
        )


def test_surfaces_memories_not_viewed_for_14_days(test_settings: Settings) -> None:
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="stale",
        goal="Kubernetes cert",
        last_viewed=(now - timedelta(days=20)).isoformat(),
        title="Pods",
    )
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="fresh",
        goal="Kubernetes cert",
        last_viewed=(now - timedelta(days=2)).isoformat(),
        title="Services",
    )

    out = ReviewAgent(test_settings).queue(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=ReviewQueueRequest(stale_days=14),
        now=now,
    )
    assert [item.video_id for item in out.items] == ["stale"]
    assert out.items[0].days_since_view == 20
    assert "Kubernetes cert" in out.items[0].prompt


def test_never_viewed_goal_memory_is_prioritized(test_settings: Settings) -> None:
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="never",
        goal="System design",
        last_viewed=None,
    )
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="old",
        goal="System design",
        last_viewed=(now - timedelta(days=90)).isoformat(),
    )
    out = ReviewAgent(test_settings).queue(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=ReviewQueueRequest(stale_days=14),
        now=now,
    )
    assert [item.video_id for item in out.items][:2] == ["never", "old"]


def test_goal_filter_and_tenant_isolation(test_settings: Settings) -> None:
    _seed(
        test_settings,
        user_id="user-a",
        video_id="a",
        goal="Python",
        last_viewed=None,
    )
    _seed(
        test_settings,
        user_id="user-a",
        video_id="b",
        goal="Networking",
        last_viewed=None,
    )
    _seed(
        test_settings,
        user_id="user-b",
        video_id="secret",
        goal="Python",
        last_viewed=None,
    )
    out = ReviewAgent(test_settings).queue(
        user_id="user-a",
        request=ReviewQueueRequest(goal="python"),
    )
    assert [item.video_id for item in out.items] == ["a"]


def test_review_queue_api_uses_authenticated_user(client: TestClient, test_settings: Settings) -> None:
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="mine",
        goal="AI",
        last_viewed=None,
    )
    _seed(
        test_settings,
        user_id="other",
        video_id="theirs",
        goal="AI",
        last_viewed=None,
    )
    resp = client.post("/api/v1/agents/review/queue", json={"stale_days": 14, "limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert [item["video_id"] for item in body["items"]] == ["mine"]

"""Reverse Memory regression tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.schema import migrate
from app.models.reverse_memory import ReverseMemoryRequest
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.reverse_memory_service import ReverseMemoryService


def _seed(
    settings: Settings,
    *,
    user_id: str,
    video_id: str,
    goal: str,
    channel: str,
    last_viewed: str | None,
) -> None:
    migrate(settings)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute(
            """
            INSERT INTO video_registry
                (user_id, video_id, url, title, channel, saved_at, last_viewed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                video_id,
                f"https://youtu.be/{video_id}",
                f"Memory {video_id}",
                channel,
                now,
                last_viewed,
            ),
        )
        conn.execute(
            """
            INSERT INTO video_reflection
                (user_id, video_id, save_reason, goal, reflection_note,
                 recommendations_enabled, preferred_creator_only,
                 allow_other_creators, difficulty, preferred_style)
            VALUES (?, ?, 'learn', ?, '', 0, 0, 1, '', '')
            """,
            (user_id, video_id, goal),
        )


def test_zero_coverage_goal_gets_foundation_first(test_settings: Settings) -> None:
    out = ReverseMemoryService(test_settings).suggest(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=ReverseMemoryRequest(goals=["Distributed systems"]),
    )
    assert out.goals_analyzed == 1
    assert out.total == 1
    item = out.suggestions[0]
    assert item.goal == "Distributed systems"
    assert item.priority == 1
    assert item.kind == "start_foundation"
    assert "foundational" in item.action.lower()
    assert item.evidence["memory_count"] == 0


def test_stale_existing_memory_is_reviewed_before_more_collection(test_settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="a",
        goal="Kubernetes",
        channel="A",
        last_viewed=(now - timedelta(days=60)).isoformat(),
    )
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="b",
        goal="Kubernetes",
        channel="A",
        last_viewed=(now - timedelta(days=60)).isoformat(),
    )

    out = ReverseMemoryService(test_settings).suggest(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=ReverseMemoryRequest(min_memories=3, min_sources=2, stale_days=30),
    )
    kinds = [item.kind for item in out.suggestions]
    assert kinds[0] == "review_existing"
    assert "expand_coverage" in kinds
    assert "diversify_sources" in kinds


def test_well_covered_goal_produces_no_suggestion(test_settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    for idx, channel in enumerate(("A", "B", "C"), start=1):
        _seed(
            test_settings,
            user_id=LOCAL_DEFAULT_USER_ID,
            video_id=f"m{idx}",
            goal="System Design",
            channel=channel,
            last_viewed=(now - timedelta(days=2)).isoformat(),
        )
    out = ReverseMemoryService(test_settings).suggest(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=ReverseMemoryRequest(min_memories=3, min_sources=2, stale_days=30),
    )
    assert out.goals_analyzed == 1
    assert out.total == 0
    assert out.suggestions == []


def test_reverse_memory_tenant_isolation(test_settings: Settings) -> None:
    _seed(
        test_settings,
        user_id="user-a",
        video_id="mine",
        goal="Python",
        channel="Mine",
        last_viewed=None,
    )
    _seed(
        test_settings,
        user_id="user-b",
        video_id="secret",
        goal="Private Goal",
        channel="Other",
        last_viewed=None,
    )
    out = ReverseMemoryService(test_settings).suggest(
        user_id="user-a",
        request=ReverseMemoryRequest(),
    )
    assert out.goals_analyzed == 1
    assert all(item.goal == "Python" for item in out.suggestions)
    assert "Private Goal" not in str(out.model_dump())


def test_reverse_memory_api_uses_authenticated_user(client: TestClient, test_settings: Settings) -> None:
    _seed(
        test_settings,
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id="mine",
        goal="Networking",
        channel="Mine",
        last_viewed=None,
    )
    _seed(
        test_settings,
        user_id="other",
        video_id="theirs",
        goal="Secret Goal",
        channel="Other",
        last_viewed=None,
    )
    resp = client.post(
        "/api/v1/intelligence/reverse-memory",
        json={"min_memories": 3, "min_sources": 2, "stale_days": 30},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["goals_analyzed"] == 1
    assert all(item["goal"] == "Networking" for item in body["suggestions"])
    assert "Secret Goal" not in str(body)

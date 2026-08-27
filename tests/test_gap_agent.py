"""Phase 4 Gap Agent regression tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.schema import migrate
from app.models.gap_agent import GapAnalysisRequest
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.gap_agent import GapAgent


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


def test_explicit_goal_with_no_memories_reports_actionable_gap(test_settings: Settings) -> None:
    out = GapAgent(test_settings).analyze(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=GapAnalysisRequest(goals=["Kubernetes"], min_memories=3, min_sources=2),
    )
    assert out.goals_analyzed == 1
    assert out.goals_with_gaps == 1
    report = out.reports[0]
    assert report.goal == "Kubernetes"
    assert report.memory_count == 0
    assert {finding.kind for finding in report.findings} == {"coverage", "source_diversity"}
    assert all(finding.action for finding in report.findings)


def test_well_covered_recent_goal_has_no_gap(test_settings: Settings) -> None:
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    for idx, channel in enumerate(("A", "B", "C"), start=1):
        _seed(
            test_settings,
            user_id=LOCAL_DEFAULT_USER_ID,
            video_id=f"m{idx}",
            goal="System Design",
            channel=channel,
            last_viewed=(now - timedelta(days=2)).isoformat(),
        )
    out = GapAgent(test_settings).analyze(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=GapAnalysisRequest(min_memories=3, min_sources=2, stale_days=30),
        now=now,
    )
    assert out.goals_analyzed == 1
    assert out.goals_with_gaps == 0
    assert out.reports == []


def test_stale_and_single_source_goal_reports_evidence(test_settings: Settings) -> None:
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    for idx in range(3):
        _seed(
            test_settings,
            user_id=LOCAL_DEFAULT_USER_ID,
            video_id=f"ai{idx}",
            goal="AI Agents",
            channel="Same Creator",
            last_viewed=None if idx == 0 else (now - timedelta(days=45)).isoformat(),
        )
    out = GapAgent(test_settings).analyze(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=GapAnalysisRequest(min_memories=3, min_sources=2, stale_days=30),
        now=now,
    )
    report = out.reports[0]
    assert report.memory_count == 3
    assert report.distinct_sources == 1
    assert report.stale_or_never_viewed == 3
    assert {finding.kind for finding in report.findings} == {"source_diversity", "review"}


def test_goal_discovery_and_tenant_isolation(test_settings: Settings) -> None:
    _seed(
        test_settings,
        user_id="user-a",
        video_id="mine",
        goal="Python",
        channel="A",
        last_viewed=None,
    )
    _seed(
        test_settings,
        user_id="user-b",
        video_id="secret",
        goal="Secret Goal",
        channel="B",
        last_viewed=None,
    )
    out = GapAgent(test_settings).analyze(
        user_id="user-a",
        request=GapAnalysisRequest(),
    )
    assert out.goals_analyzed == 1
    assert [report.goal for report in out.reports] == ["Python"]
    assert "Secret Goal" not in str(out.model_dump())


def test_gap_api_uses_authenticated_user(client: TestClient, test_settings: Settings) -> None:
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
        goal="Private Goal",
        channel="Other",
        last_viewed=None,
    )
    resp = client.post(
        "/api/v1/agents/gaps/analyze",
        json={"min_memories": 3, "min_sources": 2, "stale_days": 30},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["goals_analyzed"] == 1
    assert [report["goal"] for report in body["reports"]] == ["Networking"]

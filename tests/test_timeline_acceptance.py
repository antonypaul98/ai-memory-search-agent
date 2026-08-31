"""U-02 Memory timeline acceptance regressions."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.models.intelligence import TimelineMode, TimelineResponse


ROOT = Path(__file__).resolve().parents[1]


def test_timeline_ui_supports_date_grouping_and_goal_topic_filter() -> None:
    timeline = (ROOT / "app/static/js/views/timeline.js").read_text(encoding="utf-8")

    # Date browsing: explicit day/week/month grouping, plus chronological modes.
    assert 'value="day"' in timeline
    assert 'value="week"' in timeline
    assert 'value="month"' in timeline
    assert 'value="recently_saved"' in timeline
    assert 'value="first_learned"' in timeline

    # Goals are promoted to project topics by MemoryIntelligenceService.on_memory_indexed,
    # so the tenant-scoped topic filter is also the goal-browse path.
    assert 'id="tl-topic"' in timeline
    assert "Api.timeline(mode, topic" in timeline


def test_timeline_api_forwards_tenant_and_goal_topic(client: TestClient) -> None:
    captured: dict[str, object] = {}

    def fake_timeline(self, *, user_id, mode, topic, limit):
        captured.update(user_id=user_id, mode=mode, topic=topic, limit=limit)
        return TimelineResponse(mode=mode, topic=topic, entries=[])

    with patch(
        "app.services.memory_intelligence_service.MemoryIntelligenceService.timeline",
        fake_timeline,
    ):
        response = client.get(
            "/api/v1/intelligence/timeline",
            params={"mode": "recently_saved", "topic": "Land a security role", "limit": 17},
        )

    assert response.status_code == 200
    assert captured["user_id"]
    assert captured["mode"] == TimelineMode.RECENTLY_SAVED
    assert captured["topic"] == "Land a security role"
    assert captured["limit"] == 17
    assert response.json()["topic"] == "Land a security role"


def test_saved_goal_is_indexed_as_project_topic() -> None:
    service = (ROOT / "app/services/memory_intelligence_service.py").read_text(encoding="utf-8")
    assert "if reflection and reflection.goal:" in service
    assert "name=reflection.goal" in service
    assert "category=TopicCategory.PROJECT" in service

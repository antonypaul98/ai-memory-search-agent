"""Contract tests for evidence-backed Home Agent presence events."""

from datetime import datetime, timezone

import pytest

from app.services.home_agent.presence_events import HomePresenceEvent


def test_departure_event_preserves_evidence_and_normalizes_utc():
    event = HomePresenceEvent(
        kind="home_departure",
        occurred_at_utc=datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc),
        confidence=0.95,
        source_id="front-door-camera",
        evidence_id="frame-123",
    )

    assert event.kind == "home_departure"
    assert event.occurred_at_utc == datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)
    assert event.confidence == 0.95
    assert event.source_id == "front-door-camera"
    assert event.evidence_id == "frame-123"


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_id": ""},
        {"evidence_id": ""},
        {"confidence": -0.01},
        {"confidence": 1.01},
        {"occurred_at_utc": datetime(2026, 9, 22, 14, 30)},
    ],
)
def test_presence_event_rejects_unverifiable_or_invalid_anchor(overrides):
    values = {
        "kind": "home_departure",
        "occurred_at_utc": datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc),
        "confidence": 0.9,
        "source_id": "door-sensor",
        "evidence_id": "event-1",
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        HomePresenceEvent(**values)

from datetime import datetime, timezone

import pytest

from app.services.home_agent.image_ingest import DetectedObject
from app.services.home_agent.person_presence_adapter import presence_observation_from_detections

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def detected(name: str, confidence: float) -> DetectedObject:
    return DetectedObject(name, confidence, (0.1, 0.1, 0.5, 0.8))


def adapt(items):
    return presence_observation_from_detections(
        detections=items,
        observed_at=NOW,
        source_id="front-door-camera",
        evidence_id="frame-123",
    )


def test_person_detection_becomes_home_with_strongest_person_score():
    observation = adapt([detected("person", 0.82), detected("person", 0.93), detected("keys", 0.99)])
    assert observation.state == "home"
    assert observation.confidence == 0.93
    assert observation.source_id == "front-door-camera"
    assert observation.evidence_id == "frame-123"


def test_empty_frame_becomes_high_confidence_away():
    observation = adapt([])
    assert observation.state == "away"
    assert observation.confidence == 1.0


def test_non_person_detection_reduces_away_confidence():
    observation = adapt([detected("keys", 0.9)])
    assert observation.state == "away"
    assert observation.confidence == pytest.approx(0.1)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError):
        presence_observation_from_detections(
            detections=[], observed_at=datetime(2026, 9, 23, 12, 0),
            source_id="front-door-camera", evidence_id="frame-123",
        )

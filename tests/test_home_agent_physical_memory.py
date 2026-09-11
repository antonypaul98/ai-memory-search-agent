from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent import ObjectSighting, PhysicalMemoryIndex


def _sighting(*, location: str, minutes: int, confidence: float = 0.9, evidence_id: str) -> ObjectSighting:
    return ObjectSighting(
        object_name="keys",
        location=location,
        observed_at=datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        confidence=confidence,
        source_id="camera-living-room",
        evidence_id=evidence_id,
    )


def test_latest_returns_newest_matching_sighting() -> None:
    index = PhysicalMemoryIndex(
        [
            _sighting(location="entry table", minutes=1, evidence_id="frame-1"),
            _sighting(location="kitchen counter", minutes=5, evidence_id="frame-2"),
        ]
    )

    result = index.latest("KEYS")

    assert result is not None
    assert result.location == "kitchen counter"


def test_duplicate_evidence_is_rejected_deterministically() -> None:
    index = PhysicalMemoryIndex()
    sighting = _sighting(location="entry table", minutes=1, evidence_id="frame-1")

    assert index.add(sighting) is True
    assert index.add(sighting) is False
    assert len(index.history("keys")) == 1


def test_low_confidence_sighting_can_be_excluded() -> None:
    index = PhysicalMemoryIndex(
        [_sighting(location="sofa", minutes=3, confidence=0.4, evidence_id="frame-low")]
    )

    assert index.latest("keys", min_confidence=0.5) is None
    assert index.answer_where("keys") is None


def test_answer_where_includes_location_and_timestamp() -> None:
    index = PhysicalMemoryIndex(
        [_sighting(location="desk", minutes=7, evidence_id="frame-answer")]
    )

    answer = index.answer_where("keys")

    assert answer is not None
    assert "desk" in answer
    assert "2026-09-10" in answer


def test_sighting_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ObjectSighting(
            object_name="keys",
            location="desk",
            observed_at=datetime(2026, 9, 10, 18, 0),
            confidence=0.9,
            source_id="camera-1",
            evidence_id="frame-1",
        )


def test_sighting_validates_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        _sighting(location="desk", minutes=1, confidence=1.1, evidence_id="frame-1")

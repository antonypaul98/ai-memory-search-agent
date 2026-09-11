"""Regression tests for the Home Agent vision observation adapter."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.home_agent.observation_ingest import (
    PHYSICAL_OBSERVATION_SCOPE,
    HomeObservationIngestService,
    ObservationConsent,
)
from app.services.home_agent.vision_adapter import ConsentGatedVisionAdapter, VisionDetection


NOW = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)


def _detection(*, source_id: str = "camera-entry") -> VisionDetection:
    return VisionDetection(
        object_name="keys",
        location="entry table",
        observed_at=NOW - timedelta(seconds=10),
        confidence=0.93,
        source_id=source_id,
        evidence_id="frame-entry-0001:keys",
    )


def _consent(*, source_id: str = "camera-entry") -> ObservationConsent:
    return ObservationConsent(
        user_id="user-a",
        source_id=source_id,
        scope=PHYSICAL_OBSERVATION_SCOPE,
        granted_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
    )


def test_adapter_preserves_detection_provenance_and_uses_consent_gate() -> None:
    store = MagicMock()
    store.store_sighting.return_value = True
    adapter = ConsentGatedVisionAdapter(HomeObservationIngestService(store))

    assert adapter.ingest_detection(
        user_id="user-a",
        detection=_detection(),
        consent=_consent(),
        now=NOW,
    ) is True

    sighting = store.store_sighting.call_args.kwargs["sighting"]
    assert store.store_sighting.call_args.kwargs["user_id"] == "user-a"
    assert sighting.object_name == "keys"
    assert sighting.location == "entry table"
    assert sighting.source_id == "camera-entry"
    assert sighting.evidence_id == "frame-entry-0001:keys"
    assert sighting.confidence == 0.93
    assert sighting.observed_at == NOW - timedelta(seconds=10)


def test_adapter_cannot_persist_detection_for_unconsented_source() -> None:
    store = MagicMock()
    adapter = ConsentGatedVisionAdapter(HomeObservationIngestService(store))

    with pytest.raises(PermissionError):
        adapter.ingest_detection(
            user_id="user-a",
            detection=_detection(source_id="camera-office"),
            consent=_consent(source_id="camera-entry"),
            now=NOW,
        )

    store.store_sighting.assert_not_called()


def test_adapter_rejects_detection_without_evidence_id_before_persistence() -> None:
    store = MagicMock()
    adapter = ConsentGatedVisionAdapter(HomeObservationIngestService(store))
    detection = VisionDetection(
        object_name="keys",
        location="entry table",
        observed_at=NOW,
        confidence=0.93,
        source_id="camera-entry",
        evidence_id="",
    )

    with pytest.raises(ValueError, match="evidence_id"):
        adapter.ingest_detection(
            user_id="user-a",
            detection=detection,
            consent=_consent(),
            now=NOW,
        )

    store.store_sighting.assert_not_called()

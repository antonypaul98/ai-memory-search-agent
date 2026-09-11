"""Regression tests for bounded Home Agent vision capture sessions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.home_agent.capture_session import (
    MAX_CAPTURE_SESSION_TTL,
    BoundedVisionCaptureService,
)
from app.services.home_agent.observation_ingest import (
    PHYSICAL_OBSERVATION_SCOPE,
    HomeObservationIngestService,
    ObservationConsent,
)
from app.services.home_agent.vision_adapter import ConsentGatedVisionAdapter, VisionDetection


NOW = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)


def _service(store: MagicMock) -> BoundedVisionCaptureService:
    store.store_sighting.return_value = True
    return BoundedVisionCaptureService(
        ConsentGatedVisionAdapter(HomeObservationIngestService(store))
    )


def _detection(*, source_id: str = "camera-entry", observed_at: datetime = NOW) -> VisionDetection:
    return VisionDetection(
        object_name="wallet",
        location="entry table",
        observed_at=observed_at,
        confidence=0.96,
        source_id=source_id,
        evidence_id="frame-entry-0042:wallet",
    )


def _consent(*, user_id: str = "user-a", source_id: str = "camera-entry") -> ObservationConsent:
    return ObservationConsent(
        user_id=user_id,
        source_id=source_id,
        scope=PHYSICAL_OBSERVATION_SCOPE,
        granted_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def test_active_session_allows_detection_through_existing_consent_gate() -> None:
    store = MagicMock()
    service = _service(store)
    session = service.start_session(user_id="user-a", source_id="camera-entry", now=NOW)

    assert service.ingest_detection(
        user_id="user-a",
        session=session,
        detection=_detection(observed_at=NOW + timedelta(seconds=30)),
        consent=_consent(),
        now=NOW + timedelta(seconds=30),
    ) is True

    store.store_sighting.assert_called_once()


def test_expired_session_rejects_detection_before_persistence() -> None:
    store = MagicMock()
    service = _service(store)
    session = service.start_session(
        user_id="user-a",
        source_id="camera-entry",
        now=NOW,
        ttl=timedelta(seconds=30),
    )

    with pytest.raises(PermissionError, match="capture session"):
        service.ingest_detection(
            user_id="user-a",
            session=session,
            detection=_detection(observed_at=NOW + timedelta(seconds=31)),
            consent=_consent(),
            now=NOW + timedelta(seconds=31),
        )

    store.store_sighting.assert_not_called()


def test_session_cannot_be_reused_for_another_user_or_camera_source() -> None:
    store = MagicMock()
    service = _service(store)
    session = service.start_session(user_id="user-a", source_id="camera-entry", now=NOW)

    with pytest.raises(PermissionError):
        service.ingest_detection(
            user_id="user-b",
            session=session,
            detection=_detection(),
            consent=_consent(user_id="user-b"),
            now=NOW,
        )

    with pytest.raises(PermissionError):
        service.ingest_detection(
            user_id="user-a",
            session=session,
            detection=_detection(source_id="camera-office"),
            consent=_consent(source_id="camera-office"),
            now=NOW,
        )

    store.store_sighting.assert_not_called()


def test_detection_timestamp_must_fall_inside_capture_window() -> None:
    store = MagicMock()
    service = _service(store)
    session = service.start_session(user_id="user-a", source_id="camera-entry", now=NOW)

    with pytest.raises(PermissionError):
        service.ingest_detection(
            user_id="user-a",
            session=session,
            detection=_detection(observed_at=NOW - timedelta(seconds=1)),
            consent=_consent(),
            now=NOW + timedelta(seconds=1),
        )

    store.store_sighting.assert_not_called()


def test_session_duration_is_hard_capped() -> None:
    store = MagicMock()
    service = _service(store)

    with pytest.raises(ValueError, match="maximum"):
        service.start_session(
            user_id="user-a",
            source_id="camera-entry",
            now=NOW,
            ttl=MAX_CAPTURE_SESSION_TTL + timedelta(seconds=1),
        )

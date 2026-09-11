"""Regression tests for consent-gated Home Agent observation ingestion."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.home_agent.observation_ingest import (
    PHYSICAL_OBSERVATION_SCOPE,
    HomeObservationIngestService,
    ObservationConsent,
)
from app.services.home_agent.physical_memory import ObjectSighting


NOW = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def _sighting(source_id: str = "camera-entry") -> ObjectSighting:
    return ObjectSighting(
        object_name="keys",
        location="entry table",
        observed_at=NOW - timedelta(minutes=1),
        confidence=0.94,
        source_id=source_id,
        evidence_id="evidence-1",
    )


def _consent(
    *,
    user_id: str = "user-a",
    source_id: str = "camera-entry",
    scope: str = PHYSICAL_OBSERVATION_SCOPE,
    expires_at: datetime | None = None,
) -> ObservationConsent:
    return ObservationConsent(
        user_id=user_id,
        source_id=source_id,
        scope=scope,
        granted_at=NOW - timedelta(hours=1),
        expires_at=expires_at,
    )


def test_ingest_persists_only_with_matching_consent() -> None:
    store = MagicMock()
    store.store_sighting.return_value = True
    service = HomeObservationIngestService(store)
    sighting = _sighting()

    assert service.ingest(
        user_id="user-a",
        sighting=sighting,
        consent=_consent(),
        now=NOW,
    ) is True
    store.store_sighting.assert_called_once_with(user_id="user-a", sighting=sighting)


@pytest.mark.parametrize(
    "consent",
    [
        _consent(user_id="other-user"),
        _consent(source_id="camera-office"),
        _consent(scope="home_agent.query"),
        _consent(expires_at=NOW - timedelta(seconds=1)),
    ],
)
def test_ingest_rejects_mismatched_or_expired_consent(consent: ObservationConsent) -> None:
    store = MagicMock()
    service = HomeObservationIngestService(store)

    with pytest.raises(PermissionError):
        service.ingest(user_id="user-a", sighting=_sighting(), consent=consent, now=NOW)

    store.store_sighting.assert_not_called()


def test_consent_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="granted_at"):
        ObservationConsent(
            user_id="user-a",
            source_id="camera-entry",
            scope=PHYSICAL_OBSERVATION_SCOPE,
            granted_at=datetime(2026, 9, 11, 8, 0),
        )

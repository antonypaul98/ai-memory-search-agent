from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.services.home_agent.image_ingest import DetectedObject, HomeImageIngestService, canonical_id
from app.services.home_agent.observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE

NOW = datetime(2026, 9, 13, 20, tzinfo=timezone.utc)


def image_bytes():
    buffer = BytesIO()
    Image.new("RGB", (24, 16), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def consent(user="owner", source="phone"):
    return ObservationConsent(user, source, PHYSICAL_OBSERVATION_SCOPE, NOW - timedelta(hours=1))


def inputs(**changes):
    values = dict(user_id="owner", image_bytes=image_bytes(), source_id="phone", location="kitchen counter",
                  observed_at=NOW - timedelta(minutes=1), consent=consent(), now=NOW)
    values.update(changes)
    return values


def service():
    store = MagicMock()
    store.store_image_batch.return_value = {"stored_observations": 1}
    detector = MagicMock(detector_id="fixture-detector-v1")
    detector.detect.return_value = [DetectedObject("  KEYS  ", 0.91, (0.1, 0.1, 0.5, 0.5))]
    return HomeImageIngestService(store, detector), store, detector


def test_real_image_decode_canonical_class_and_evidence_provenance():
    ingest, store, detector = service()
    result = ingest.ingest(**inputs())
    batch = store.store_image_batch.call_args.args[0]
    assert batch.detections[0].object_class == "keys"
    assert batch.detections[0].confidence == 0.91
    assert batch.location == "kitchen counter"
    assert batch.detector_id == "fixture-detector-v1"
    assert batch.source_id == "phone"
    assert batch.observed_at == NOW - timedelta(minutes=1)
    assert Image.open(BytesIO(batch.image_bytes)).size == (24, 16)
    assert detector.detect.call_args.args[0].mode == "RGB"
    assert result["detection_ms"] >= 0
    ingest.ingest(**inputs())
    assert store.store_image_batch.call_args.args[0].frame_id == batch.frame_id
    assert canonical_id("object", "owner", "keys") != canonical_id("object", "other", "keys")


@pytest.mark.parametrize("changes", [
    {"user_id": "other"}, {"source_id": "other"},
    {"consent": ObservationConsent("owner", "phone", PHYSICAL_OBSERVATION_SCOPE, NOW + timedelta(seconds=1))},
])
def test_rejects_consent_before_processing_private_pixels(changes):
    ingest, store, detector = service()
    with pytest.raises(PermissionError):
        ingest.ingest(**inputs(**changes))
    detector.detect.assert_not_called()
    store.store_image_batch.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"location": " "}, {"observed_at": NOW.replace(tzinfo=None)},
    {"observed_at": NOW + timedelta(seconds=1)}, {"image_bytes": b"not an image"},
    {"image_bytes": b""}, {"image_bytes": b"x" * (10 * 1024 * 1024 + 1)},
])
def test_malformed_image_metadata_never_persisted(changes):
    ingest, store, detector = service()
    with pytest.raises((ValueError, OSError)):
        ingest.ingest(**inputs(**changes))
    store.store_image_batch.assert_not_called()
    detector.detect.assert_not_called()


@pytest.mark.parametrize("score,box", [(float("nan"), (0, 0, 1, 1)), (1.1, (0, 0, 1, 1)),
                                       (0.9, (1, 0, 0, 1)), (0.9, (0, 0, float("inf"), 1))])
def test_invalid_detector_output(score, box):
    with pytest.raises(ValueError):
        DetectedObject("keys", score, box)


def test_detector_failure_never_persists_evidence():
    ingest, store, detector = service()
    detector.detect.side_effect = RuntimeError("detector failed")
    with pytest.raises(RuntimeError):
        ingest.ingest(**inputs())
    store.store_image_batch.assert_not_called()



def test_consent_expiring_during_detection_prevents_retention(monkeypatch):
    from app.services.home_agent import image_ingest
    ticks = iter([0, 0, 61, 61])
    monkeypatch.setattr(image_ingest, "perf_counter", lambda: next(ticks))
    ingest, store, detector = service()
    grant = ObservationConsent("owner", "phone", PHYSICAL_OBSERVATION_SCOPE, NOW,
                               NOW + timedelta(seconds=60))
    with pytest.raises(PermissionError, match="expired during detection"):
        ingest.ingest(**inputs(consent=grant))
    detector.detect.assert_called_once()
    store.store_image_batch.assert_not_called()

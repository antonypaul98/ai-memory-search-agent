"""Opt-in trained-detector + real Postgres acceptance on pinned public sample data.

Run with a disposable MEMORY_AGENT_TEST_POSTGRES_DSN. Model/sample downloads
happen here, never in the private-image ingestion path.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from huggingface_hub import hf_hub_download, snapshot_download
from app.config import Settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.services.home_agent.image_ingest import HomeImageIngestService
from app.services.home_agent.observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE
from app.services.home_agent.owlvit_detector import LocalOwlViTDetector
from app.services.home_agent.query_service import HomeAgentQueryService

MODEL_REVISION = "cbc355fb364588351c5d51c7f74465e8e7ec6f72"


def run_one_camera_photo_replay(*, image_path: Path, detector) -> dict:
    """Repeatable *software* replay of real photo detections through event evidence.

    The second scan is deliberately an empty simulated detector result; the
    third reuses the same public photo. This does NOT prove real camera exit,
    motion, or physical-instance identity.
    """
    from tempfile import TemporaryDirectory
    from PIL import Image
    from app.services.home_agent.frame_inventory import FrameInventory
    from app.services.home_agent.frame_event_log import PrivateFrameEventLog
    from app.services.home_agent.frame_evidence import PrivateFrameEvidenceStore
    from app.services.home_agent.live_preview import (
        normalized_to_pixels, reconcile_tracks, suppress_duplicates,
    )

    with Image.open(image_path) as original:
        image = original.convert("RGB")
    width, height = image.size
    detections = detector.detect(image)
    boxes = suppress_duplicates([
        box for item in detections
        if (box := normalized_to_pixels(item, width, height)) is not None
    ])
    assert boxes, "trained model produced no public-photo frame detections"
    inventory = FrameInventory()
    tracks, next_id = reconcile_tracks({}, boxes, 1.0, 1)
    with TemporaryDirectory(prefix="home-one-camera-replay-") as root:
        directory = Path(root)
        evidence = PrivateFrameEvidenceStore(directory / "events-evidence")
        with PrivateFrameEventLog(directory / "events.jsonl", camera_id="public-photo-replay",
                                  room_name="synthetic-single-room") as journal:
            # One trained real-photo scan, one *simulated* missing scan, then
            # another trained observation of the identical public photo.
            for scan_at, visible_tracks in (
                (1.0, tracks), (2.0, {}),
                (3.0, reconcile_tracks(tracks, boxes, 3.0, next_id)[0]),
            ):
                events = inventory.update(visible_tracks, scan_at=scan_at,
                                          width=width, height=height)
                references = evidence.record_scan(image=image, visible=inventory.visible,
                                                  events=events)
                journal.append_scan(scan_at=scan_at, visible=inventory.visible,
                                    events=events, evidence_files=references)
        rows = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
        assert len(rows) == 3 and rows[0]["visible"] and rows[1]["visible"] == []
        assert rows[2]["visible"], "public-photo reappearance should be visible"
        statuses = [[event["status"] for event in row["events"]] for row in rows]
        assert "VISIBLE" in statuses[0]
        assert "NOT_VISIBLE" in statuses[1] or "POSSIBLE_EXIT" in statuses[1]
        assert "REAPPEARED_TENTATIVE" in statuses[2]
        for row in rows:
            for event in row["events"]:
                assert event["identity_verified"] is False
                ref = event["evidence_image"]
                assert ref and (directory / ref).is_file(), "event image link missing"
        return {"result": "passed", "source": "pinned_public_photo",
                "missing_scan": "simulated", "reentry_identity": "tentative",
                "real_camera": False, "statuses": statuses,
                "event_images": sum(len(row["events"]) for row in rows)}


def main():
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        raise RuntimeError("a disposable MEMORY_AGENT_TEST_POSTGRES_DSN is required")
    model_path = snapshot_download("google/owlvit-base-patch32", revision=MODEL_REVISION,
        allow_patterns=["*.json", "*.txt", "pytorch_model.bin"])
    image_path = hf_hub_download("huggingface/documentation-images", "coco_sample.png", repo_type="dataset",
                                 revision="541575dc4c26c063abbd2a259c740835e88a3e6d")
    detector = LocalOwlViTDetector(model_path, labels=["cat", "remote control"], threshold=.2)
    print(json.dumps({"one_camera_event_replay": run_one_camera_photo_replay(\n        image_path=Path(image_path), detector=detector)}))\n    factory = get_postgres_connection_factory(Settings(postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN"))
    store = PostgresHomeImageStore(factory)
    tenant = "trained-vision-smoke-" + uuid4().hex
    now = datetime.now(timezone.utc)
    consent = ObservationConsent(tenant, "public-fixture", PHYSICAL_OBSERVATION_SCOPE, now)
    frames = []
    try:
        for location, observed_at in [("demo office", now-timedelta(hours=2)), ("demo living room", now-timedelta(minutes=1))]:
            result = HomeImageIngestService(store, detector).ingest(
                user_id=tenant, image_bytes=Path(image_path).read_bytes(), source_id="public-fixture",
                location=location, observed_at=observed_at, consent=consent)
            if result["frame_id"]:
                frames.append(result["frame_id"])
            assert result["stored_observations"] > 0, "trained detector produced no observations"
        restarted = PostgresHomeImageStore(factory)
        query = HomeAgentQueryService(restarted)
        answer = query.where_is(user_id=tenant, object_name="cat", min_confidence=.2)
        assert answer is not None and answer.location == "demo living room"
        assert answer.observed_at == (now-timedelta(minutes=1)).isoformat()
        provenance = restarted.describe_observation(user_id=tenant, observation_id=answer.evidence_id)
        assert provenance["identity_kind"] == "class"
        assert restarted.get_image(user_id=tenant, frame_id=provenance["frame_id"])
        assert restarted.get_image(user_id=tenant+"-other", frame_id=provenance["frame_id"]) is None

        # Two class-level detections at different locations do not establish
        # that the same physical cat moved. The legacy movement query must
        # fail closed until independent instance-identity evidence is present.
        assert query.movement_history(
            user_id=tenant, object_name="cat", min_confidence=.2, limit=20
        ) == [], "class-only observations must not assert a physical movement"
        assert query.before_location(
            user_id=tenant, object_name="cat",
            location="demo living room", min_confidence=.2
        ) is None, "class-only observations must not assert a prior location"
        assert query.observed_location_changes(
            user_id=tenant, object_name="cat", min_confidence=.9
        ) == [], "unverified instance associations must not produce changes"
        assert query.observed_location_changes(
            user_id=tenant+"-other", object_name="cat", min_confidence=.9
        ) == [], "cross-tenant verified instance observations must remain isolated"
        assert query.movement_history(
            user_id=tenant+"-other", object_name="cat",
            min_confidence=.2, limit=20
        ) == []

        print(json.dumps({"result": "passed", "model_revision": MODEL_REVISION,
            "detector_id": detector.detector_id, "location": answer.location,
            "confidence": answer.confidence, "detection_ms": result["detection_ms"],
            "ingestion_ms": result["ingestion_ms"], "evidence_linked": True,
            "class_only_movement_rejected": True,
            "verified_instance_changes": 0, "tenant_isolated": True}))
    finally:
        for frame_id in frames:
            store.delete_image(user_id=tenant, frame_id=frame_id)


if __name__ == "__main__":
    main()

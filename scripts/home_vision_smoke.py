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


def main():
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        raise RuntimeError("a disposable MEMORY_AGENT_TEST_POSTGRES_DSN is required")
    model_path = snapshot_download("google/owlvit-base-patch32", revision=MODEL_REVISION,
        allow_patterns=["*.json", "*.txt", "pytorch_model.bin"])
    image_path = hf_hub_download("huggingface/documentation-images", "coco_sample.png", repo_type="dataset",
                                 revision="541575dc4c26c063abbd2a259c740835e88a3e6d")
    detector = LocalOwlViTDetector(model_path, labels=["cat", "remote control"], threshold=.2)
    factory = get_postgres_connection_factory(Settings(postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN"))
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
        answer = HomeAgentQueryService(restarted).where_is(user_id=tenant, object_name="cat", min_confidence=.2)
        assert answer is not None and answer.location == "demo living room"
        assert answer.observed_at == (now-timedelta(minutes=1)).isoformat()
        provenance = restarted.describe_observation(user_id=tenant, observation_id=answer.evidence_id)
        assert provenance["identity_kind"] == "class"
        assert restarted.get_image(user_id=tenant, frame_id=provenance["frame_id"])
        assert restarted.get_image(user_id=tenant+"-other", frame_id=provenance["frame_id"]) is None
        print(json.dumps({"result": "passed", "model_revision": MODEL_REVISION,
            "detector_id": detector.detector_id, "location": answer.location,
            "confidence": answer.confidence, "detection_ms": result["detection_ms"],
            "ingestion_ms": result["ingestion_ms"], "evidence_linked": True}))
    finally:
        for frame_id in frames:
            store.delete_image(user_id=tenant, frame_id=frame_id)


if __name__ == "__main__":
    main()

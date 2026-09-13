"""Manual local-image demo: python -m app.services.home_agent.image_demo --help."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter

from app.config import Settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_home_image_store import PostgresHomeImageStore
from .image_ingest import HomeImageIngestService, MAX_IMAGE_BYTES
from .observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE
from .owlvit_detector import LocalOwlViTDetector
from .query_service import HomeAgentQueryService


def main():
    parser = argparse.ArgumentParser(description="Consented local image → Postgres → last-seen query")
    parser.add_argument("--image", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--tenant", required=True, help="local operator tenant; API callers must use authenticated identity")
    parser.add_argument("--source", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--observed-at", required=True, help="ISO 8601 time with timezone")
    parser.add_argument("--labels", nargs="+", required=True, help="object classes; not personal identities")
    parser.add_argument("--query", required=True, help="object class for last-seen lookup")
    parser.add_argument("--consent", action="store_true", required=True,
                        help="authorize processing and retaining this submitted image locally")
    args = parser.parse_args()
    observed_at = datetime.fromisoformat(args.observed_at)
    with Path(args.image).open("rb") as handle:
        data = handle.read(MAX_IMAGE_BYTES + 1)
    detector = LocalOwlViTDetector(args.model_path, labels=args.labels)
    store = PostgresHomeImageStore(get_postgres_connection_factory(Settings()))
    now = datetime.now(timezone.utc)
    result = HomeImageIngestService(store, detector).ingest(
        user_id=args.tenant, image_bytes=data, source_id=args.source, location=args.location,
        observed_at=observed_at, now=now,
        consent=ObservationConsent(args.tenant, args.source, PHYSICAL_OBSERVATION_SCOPE, now),
    )
    started = perf_counter()
    answer = HomeAgentQueryService(store).where_is(user_id=args.tenant, object_name=args.query, min_confidence=0.2)
    result["retrieval_ms"] = (perf_counter() - started) * 1000
    result["answer"] = asdict(answer) if answer else None
    if answer:
        result["provenance"] = store.describe_observation(user_id=args.tenant, observation_id=answer.evidence_id)
        result["text"] = "Detected class: " + answer.text
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""Local still-image ingestion. No camera access, network fetches or room inference."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
from time import perf_counter
from typing import Protocol

from PIL import Image, ImageOps

from .observation_ingest import ObservationConsent

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000


def canonical_id(kind: str, *parts: str) -> str:
    return kind + "_" + sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def normalize_class(value: str) -> str:
    value = " ".join(value.split()).casefold()
    if not value or len(value) > 100:
        raise ValueError("object class must contain 1 to 100 characters")
    return value


@dataclass(frozen=True)
class DetectedObject:
    object_class: str
    confidence: float
    # Normalized x1, y1, x2, y2. Identity is a class, never a personal instance.
    box: tuple[float, float, float, float]

    def __post_init__(self):
        object.__setattr__(self, "object_class", normalize_class(self.object_class))
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("invalid detector confidence")
        if len(self.box) != 4 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.box):
            raise ValueError("invalid bounding box")
        if self.box[0] >= self.box[2] or self.box[1] >= self.box[3]:
            raise ValueError("empty bounding box")
        object.__setattr__(self, "box", tuple(self.box))


class ImageDetector(Protocol):
    detector_id: str
    def detect(self, image: Image.Image) -> list[DetectedObject]: ...


@dataclass(frozen=True)
class ImageObservationBatch:
    user_id: str
    frame_id: str
    image_bytes: bytes
    image_sha256: str
    source_id: str
    location: str
    observed_at: datetime
    detector_id: str
    detections: tuple[DetectedObject, ...]


class ImageObservationWriter(Protocol):
    def store_image_batch(self, batch: ImageObservationBatch) -> dict: ...


class HomeImageIngestService:
    def __init__(self, store: ImageObservationWriter, detector: ImageDetector):
        self._store = store
        self._detector = detector

    def ingest(self, *, user_id: str, image_bytes: bytes, source_id: str,
               location: str, observed_at: datetime, consent: ObservationConsent,
               now: datetime | None = None) -> dict:
        started = perf_counter()
        now = now or datetime.now(timezone.utc)
        if not user_id.strip() or not source_id.strip() or not location.strip():
            raise ValueError("tenant, source and explicit location are required")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not consent.allows(user_id=user_id, source_id=source_id, now=now):
            raise PermissionError("physical observation consent is not active")
        if observed_at > now:
            raise ValueError("observation cannot be in the future")
        if not isinstance(image_bytes, bytes) or not 0 < len(image_bytes) <= MAX_IMAGE_BYTES:
            raise ValueError("image must contain at most 10 MiB")
        # Reject oversized images before decoding pixels; never trust a filename.
        with Image.open(BytesIO(image_bytes)) as original:
            if original.format not in ("JPEG", "PNG"):
                raise ValueError("only JPEG and PNG still images are supported")
            if original.width * original.height > MAX_IMAGE_PIXELS:
                raise ValueError("image exceeds pixel limit")
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("animated images are not supported")
            image = ImageOps.exif_transpose(original).convert("RGB")
        detection_started = perf_counter()
        detections = tuple(self._detector.detect(image))
        detection_ms = (perf_counter() - detection_started) * 1000
        if len(detections) > 100 or any(not isinstance(d, DetectedObject) for d in detections):
            raise ValueError("invalid or excessive detector output")
        detections = tuple(sorted(detections, key=lambda d: (-d.confidence, d.object_class, d.box)))
        if not self._detector.detector_id.strip():
            raise ValueError("detector provenance is required")
        # Retain a normalized evidence image with no EXIF/GPS metadata.
        cleaned = BytesIO()
        image.save(cleaned, format="PNG")
        retained_bytes = cleaned.getvalue()
        if len(retained_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("normalized evidence exceeds 10 MiB")
        digest = sha256(retained_bytes).hexdigest()
        stamp = observed_at.astimezone(timezone.utc)
        frame_id = canonical_id("frame", user_id, digest, source_id, location.strip(), stamp.isoformat())
        batch = ImageObservationBatch(
            user_id, frame_id, retained_bytes, digest, source_id, location.strip(), stamp,
            self._detector.detector_id, detections,
        )
        commit_time = now + timedelta(seconds=perf_counter() - started)
        if not consent.allows(user_id=user_id, source_id=source_id, now=commit_time):
            raise PermissionError("physical observation consent expired during detection")
        result = self._store.store_image_batch(batch)
        return {**result, "detection_ms": detection_ms, "ingestion_ms": (perf_counter() - started) * 1000}

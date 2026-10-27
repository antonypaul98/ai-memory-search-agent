"""Offline visual *candidate* matching for Home Agent; never physical-identity proof.

ORB features and geometric consistency can suggest that two object crops look
similar. They cannot establish persistent physical identity, particularly for
identical products, replayed frames, reflective objects, or long occlusions.
This module deliberately does NOT implement TrustedInstanceVerifier or issue
VerifiedInstanceProof. No image data is written, uploaded, or logged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class VisualSighting:
    user_id: str
    source_id: str
    observation_id: str
    observed_at: datetime
    object_class: str
    crop: Any  # local OpenCV BGR or grayscale uint8 array; held in memory only

    def __post_init__(self) -> None:
        for field in ("user_id", "source_id", "observation_id", "object_class"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} is required")
        if (not isinstance(self.observed_at, datetime)
                or self.observed_at.tzinfo is None
                or self.observed_at.utcoffset() is None):
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TentativeVisualMatch:
    """Diagnostic candidate only. Not a verified physical-instance association."""
    reference_observation_id: str
    query_observation_id: str
    inliers: int
    inlier_fraction: float


def _gray_uint8(crop: Any, cv2, np):
    if not isinstance(crop, np.ndarray) or crop.dtype != np.uint8:
        return None
    if crop.ndim not in (2, 3):
        return None
    height, width = crop.shape[:2]
    if not (64 <= height <= 2048 and 64 <= width <= 2048):
        return None
    if crop.ndim == 2:
        gray = crop
    elif crop.shape[2] == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    else:
        return None
    if not gray.flags.c_contiguous:
        gray = np.ascontiguousarray(gray)
    return gray


def _features(crop: Any, cv2, np):
    gray = _gray_uint8(crop, cv2, np)
    if gray is None:
        return None
    detector = cv2.ORB_create(nfeatures=800, fastThreshold=10)
    points, descriptors = detector.detectAndCompute(gray, None)
    if descriptors is None or len(points) < 20:
        return None
    return points, descriptors


def _geometry(a, b, cv2, np) -> tuple[int, float]:
    points_a, descriptors_a = a
    points_b, descriptors_b = b
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False).knnMatch(
        descriptors_a, descriptors_b, k=2,
    )
    good = [pair[0] for pair in pairs
            if len(pair) == 2 and pair[0].distance < 0.72 * pair[1].distance]
    if len(good) < 12:
        return 0, 0.0
    src = np.float32([points_a[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([points_b[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if mask is None:
        return 0, 0.0
    inliers = int(mask.ravel().sum())
    return inliers, inliers / len(good)


def tentative_visual_candidate(
    query: VisualSighting,
    references: Sequence[VisualSighting],
    *, max_age: timedelta = timedelta(minutes=5),
    min_inliers: int = 16,
    min_fraction: float = 0.65,
    min_margin: int = 8,
) -> TentativeVisualMatch | None:
    """Find one unambiguous visual lookalike, never a trusted identity proof.

    Requires a separate sighting ID, same authenticated tenant/camera/class,
    nonfuture reference within a bounded gap, geometric feature support, and a
    clear lead over any competing lookalike. Rejects duplicate reference IDs.
    No stored crops, face recognition, external services or identity writes.
    """
    if not isinstance(query, VisualSighting):
        raise ValueError("query must be VisualSighting")
    if not isinstance(max_age, timedelta) or not timedelta(0) < max_age <= timedelta(minutes=5):
        raise ValueError("max_age must be positive and at most five minutes")
    if (isinstance(min_inliers, bool) or not isinstance(min_inliers, int)
            or min_inliers < 12 or isinstance(min_margin, bool)
            or not isinstance(min_margin, int) or min_margin < 1
            or isinstance(min_fraction, bool) or not isinstance(min_fraction, (int, float))
            or not isfinite(min_fraction) or not 0 < min_fraction <= 1):
        raise ValueError("invalid geometric matching thresholds")
    # Optional dependency is imported only for local visual analysis.
    import cv2
    import numpy as np

    query_features = _features(query.crop, cv2, np)
    if query_features is None:
        return None
    eligible = []
    seen = set()
    for ref in references:
        if not isinstance(ref, VisualSighting):
            raise ValueError("references must be VisualSighting")
        if ref.user_id != query.user_id:
            continue
        # Observation IDs are tenant-unique provenance, not scoped to a
        # camera, class, or matching time window. A replay or collision in an
        # otherwise ineligible reference still invalidates this comparison.
        if ref.observation_id == query.observation_id or ref.observation_id in seen:
            return None
        seen.add(ref.observation_id)
        if ref.source_id != query.source_id:
            continue
        if ref.object_class.casefold() != query.object_class.casefold():
            continue
        if not timedelta(0) < query.observed_at - ref.observed_at <= max_age:
            continue
        eligible.append(ref)
    scores = []
    for ref in eligible:
        features = _features(ref.crop, cv2, np)
        if features is None:
            continue
        inliers, fraction = _geometry(query_features, features, cv2, np)
        # A near-tie must remain ambiguous even if the runner-up narrowly
        # misses the absolute acceptance thresholds. Otherwise a competing
        # lookalike can disappear from the margin check.
        if inliers > 0:
            scores.append((inliers, fraction, ref.observation_id))
    if not scores:
        return None
    scores.sort(key=lambda item: (-item[0], -item[1], item[2]))
    best = scores[0]
    if best[0] < min_inliers or best[1] < min_fraction:
        return None
    if len(scores) > 1 and best[0] - scores[1][0] < min_margin:
        return None
    return TentativeVisualMatch(best[2], query.observation_id, best[0], best[1])

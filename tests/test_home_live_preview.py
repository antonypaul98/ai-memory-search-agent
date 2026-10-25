"""Synthetic-only preview contract checks; never open a camera or load weights."""
from types import SimpleNamespace

import pytest

from app.services.home_agent.live_preview import (
    DEFAULT_LABELS, PreviewBox, Track, advance_with_optical_flow,
    normalized_to_pixels, reconcile_tracks, suppress_duplicates,
)


def test_default_labels_within_current_detector_cap():
    assert len(DEFAULT_LABELS) == 32
    assert len(set(DEFAULT_LABELS)) == 32


def test_real_home_detection_contract_scales_normalized_float_before_rounding():
    detection = SimpleNamespace(object_class="water bottle", confidence=0.204,
                                box=(0.25, 0.1, 0.75, 0.8))
    assert normalized_to_pixels(detection, 1280, 720) == PreviewBox(
        "water bottle", 0.204, (320, 72, 960, 576))


def test_invalid_or_tiny_boxes_not_drawn():
    detection = SimpleNamespace(object_class="bottle", confidence=0.2,
                                box=(0.1, 0.1, 0.1, 0.3))
    assert normalized_to_pixels(detection, 640, 480) is None
    detection.box = (0.1, 0.1, 0.10001, 0.3)
    assert normalized_to_pixels(detection, 640, 480) is None


def test_same_label_overlapping_box_preserves_tentative_id():
    original = {8: Track(8, PreviewBox("bottle", 0.5, (20, 20, 90, 100)), 2)}
    current, next_id = reconcile_tracks(original, [PreviewBox("bottle", 0.6, (30, 22, 100, 102))], 3, 9)
    assert list(current) == [8]
    assert next_id == 9


def test_new_class_or_nonoverlap_gets_new_id():
    original = {8: Track(8, PreviewBox("bottle", 0.5, (20, 20, 90, 100)), 2)}
    current, next_id = reconcile_tracks(original, [PreviewBox("cup", 0.6, (30, 22, 100, 102))], 3, 9)
    assert list(current) == [9, 8]
    assert current[8].observed_at == 2  # unmatched is last-seen, not observed now
    assert next_id == 10


def test_old_track_not_reused_after_age_limit():
    original = {8: Track(8, PreviewBox("bottle", 0.5, (20, 20, 90, 100)), 2)}
    current, _ = reconcile_tracks(original, [PreviewBox("bottle", 0.6, (20, 20, 90, 100))], 30, 9)
    assert list(current) == [9]


def test_flow_tracks_textured_synthetic_object_movement():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(42)
    old = np.zeros((160, 240), dtype=np.uint8)
    old[40:90, 50:100] = rng.integers(0, 255, (50, 50), dtype=np.uint8)
    shifted = np.zeros_like(old)
    shifted[45:95, 60:110] = old[40:90, 50:100]
    tracks = {1: Track(1, PreviewBox("box", 0.9, (50, 40, 100, 90)), 0)}
    advance_with_optical_flow(cv2, np, old, shifted, tracks)
    assert tracks[1].flow_updated
    x1, y1, x2, y2 = tracks[1].box.xyxy
    assert abs(x1 - 60) <= 2 and abs(y1 - 45) <= 2
    assert abs(x2 - 110) <= 2 and abs(y2 - 95) <= 2


def test_flow_fails_safe_when_no_features():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    old = np.zeros((120, 160), dtype=np.uint8)
    tracks = {1: Track(1, PreviewBox("bottle", 0.2, (20, 20, 80, 80)), 0)}
    advance_with_optical_flow(cv2, np, old, old.copy(), tracks)
    assert tracks[1].box.xyxy == (20, 20, 80, 80)
    assert not tracks[1].flow_updated

def test_unmatched_detection_is_bounded_last_seen_not_a_new_observation():
    original = {7: Track(7, PreviewBox("bottle", 0.8, (10, 10, 40, 60)), 1)}
    current, next_id = reconcile_tracks(original, [], 3, 8, max_age=4)
    assert list(current) == [7]
    assert current[7].observed_at == 1
    current, _ = reconcile_tracks(current, [], 6, next_id, max_age=4)
    assert current == {}


def test_nonfinite_detection_rejected():
    for invalid in [float("nan"), float("inf"), float("-inf")]:
        obj = SimpleNamespace(object_class="bottle", confidence=0.6,
                              box=(invalid, 0.2, 0.8, 0.9))
        assert normalized_to_pixels(obj, 640, 480) is None
        obj.box = (0.1, 0.2, 0.8, 0.9)
        obj.confidence = invalid
        assert normalized_to_pixels(obj, 640, 480) is None


def test_duplicate_boxes_suppressed_without_deleting_distinct_objects():
    detections = [
        PreviewBox("bottle", 0.8, (10, 10, 50, 90)),
        PreviewBox("bottle", 0.7, (11, 11, 51, 91)),
        PreviewBox("cup", 0.6, (150, 20, 190, 80)),
    ]
    assert suppress_duplicates(detections) == [detections[0], detections[2]]


def test_cross_label_same_box_suppressed_but_nested_box_retained():
    detections = [
        PreviewBox("water bottle", 0.8, (10, 10, 50, 90)),
        PreviewBox("bottle", 0.7, (10, 10, 50, 90)),
        PreviewBox("phone", 0.5, (15, 20, 30, 40)),
    ]
    assert suppress_duplicates(detections) == [detections[0], detections[2]]


def test_stale_overlay_uses_last_detector_box_not_flow_drift():
    from app.services.home_agent.live_preview import display_box
    observed = PreviewBox("floor lamp", 0.8, (10, 10, 40, 80))
    track = Track(7, observed, 0)
    track.box = PreviewBox("floor lamp", 0.8, (30, 10, 60, 80))
    assert display_box(track, 0.5).xyxy == (30, 10, 60, 80)
    assert display_box(track, 2.0).xyxy == (10, 10, 40, 80)
    assert track.last_detected_box == observed


def test_stale_track_cannot_be_dragged_by_occluder_optical_flow():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(42)
    old = np.zeros((160, 240), dtype=np.uint8)
    old[40:90, 50:100] = rng.integers(0, 255, (50, 50), dtype=np.uint8)
    shifted = np.zeros_like(old)
    shifted[45:95, 60:110] = old[40:90, 50:100]
    track = Track(1, PreviewBox("floor lamp", 0.9, (50, 40, 100, 90)), 0)
    advance_with_optical_flow(cv2, np, old, shifted, {1: track}, now=3.0)
    assert track.box.xyxy == (50, 40, 100, 90)
    assert not track.flow_updated

def test_bottle_synonym_preserves_tentative_id_across_detector_label_changes():
    original = {7: Track(7, PreviewBox("water bottle", 0.8, (10, 10, 50, 90)), 1)}
    current, next_id = reconcile_tracks(
        original, [PreviewBox("bottle", 0.9, (12, 12, 52, 92))], 2, 8
    )
    assert list(current) == [7]
    assert next_id == 8


def test_bottle_synonym_suppresses_near_duplicate_but_keeps_separate_bottle():
    detections = [
        PreviewBox("water bottle", 0.8, (10, 10, 50, 90)),
        PreviewBox("bottle", 0.7, (14, 14, 54, 94)),
        PreviewBox("bottle", 0.6, (90, 10, 130, 90)),
    ]
    assert suppress_duplicates(detections) == [detections[0], detections[2]]


@pytest.mark.parametrize("scan_at, now, max_age, expected", [
    (1.0, 3.0, 4.0, True),
    (1.0, 5.0, 4.0, True),
    (1.0, 5.001, 4.0, False),
    (10.0, 9.0, 4.0, False),
    (float("nan"), 5.0, 4.0, False),
    (1.0, float("inf"), 4.0, False),
    (1.0, 3.0, 0.0, False),
])
def test_delayed_inference_result_never_counts_as_live_detection(scan_at, now, max_age, expected):
    from app.services.home_agent.live_preview import scan_result_is_fresh
    assert scan_result_is_fresh(scan_at, now, max_age=max_age) is expected

def test_malformed_detector_coordinates_fail_closed():
    from types import SimpleNamespace
    for malformed in (0.5, iter((0.1, 0.1, 0.8, 0.8)), object()):
        detection = SimpleNamespace(
            object_class="bottle", confidence=0.7, box=malformed
        )
        assert normalized_to_pixels(detection, 640, 480) is None
    valid = SimpleNamespace(
        object_class="bottle", confidence=0.7, box=(0.1, 0.1, 0.8, 0.8)
    )
    assert normalized_to_pixels(valid, 640, 480) is not None


def test_nonfinite_optical_flow_is_ignored_without_crashing():
    np = pytest.importorskip("numpy")

    class StubFlow:
        @staticmethod
        def goodFeaturesToTrack(*args, **kwargs):
            return np.array([[[20., 20.]], [[30., 30.]], [[40., 40.]]],
                            dtype=np.float32)

        @staticmethod
        def calcOpticalFlowPyrLK(old, new, points, ignored):
            moved = points.copy()
            moved[:, :, 0] = float("nan")
            return moved, np.ones((3, 1), dtype=np.uint8), None

    before = PreviewBox("cup", 0.8, (10, 10, 70, 70))
    track = Track(1, before, 0)
    gray = np.zeros((100, 100), dtype=np.uint8)
    advance_with_optical_flow(StubFlow(), np, gray, gray.copy(), {1: track})
    assert track.box == before
    assert not track.flow_updated

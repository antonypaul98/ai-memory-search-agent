from datetime import datetime, timedelta, timezone
import pytest

# Core CI intentionally omits optional local vision dependencies; the Home
# vision smoke job installs OpenCV and executes this module without skipping.
cv2 = pytest.importorskip("cv2", reason="OpenCV is an optional Home Vision dependency")
np = pytest.importorskip("numpy", reason="NumPy is an optional Home Vision dependency")
from app.services.home_agent.visual_instance_candidate import VisualSighting, tentative_visual_candidate

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def pattern(seed):
    rng = np.random.default_rng(seed)
    canvas = np.zeros((256, 256), dtype=np.uint8)
    for _ in range(80):
        x, y = rng.integers(12, 244, size=2)
        radius = int(rng.integers(2, 7))
        cv2.circle(canvas, (int(x), int(y)), radius, int(rng.integers(100, 255)), -1)
    return canvas


def sighting(oid, crop, *, seconds=0, user='A', source='cam1', cls='mug'):
    return VisualSighting(user, source, oid, NOW+timedelta(seconds=seconds), cls, crop)


def test_same_distinctive_visual_pattern_yields_tentative_candidate_only():
    image = pattern(3)
    shifted = cv2.warpAffine(image, np.float32([[1, 0, 5], [0, 1, 7]]), (256, 256))
    result = tentative_visual_candidate(sighting('new', shifted, seconds=10),
                                        [sighting('old', image)])
    assert result is not None
    assert result.reference_observation_id == 'old'
    assert result.inliers >= 16
    assert not hasattr(result, 'instance_id')


def test_two_identical_references_reject_ambiguity():
    image = pattern(5)
    query = sighting('new', image, seconds=10)
    assert tentative_visual_candidate(query, [sighting('a', image), sighting('b', image)]) is None


def test_cross_tenant_camera_and_class_cannot_match():
    image = pattern(3)
    query = sighting('new', image, seconds=10)
    assert tentative_visual_candidate(query, [sighting('old', image, user='B')]) is None
    assert tentative_visual_candidate(query, [sighting('old', image, source='cam2')]) is None
    assert tentative_visual_candidate(query, [sighting('old', image, cls='wallet')]) is None


def test_replayed_or_duplicate_sighting_ids_fail_closed():
    image = pattern(3)
    query = sighting('new', image, seconds=10)
    assert tentative_visual_candidate(query, [sighting('new', image)]) is None
    assert tentative_visual_candidate(query, [sighting('old', image), sighting('old', image)]) is None


def test_out_of_window_and_blank_images_rejected():
    image = pattern(3)
    query = sighting('new', image, seconds=360)
    assert tentative_visual_candidate(query, [sighting('old', image)]) is None
    assert tentative_visual_candidate(sighting('new', np.zeros((256,256), dtype=np.uint8), seconds=10), [sighting('old', image)]) is None


def test_invalid_crop_and_threshold_rejected():
    image = pattern(3)
    query = sighting('new', image.astype(np.float32), seconds=10)
    assert tentative_visual_candidate(query, [sighting('old', image)]) is None
    with pytest.raises(ValueError):
        tentative_visual_candidate(sighting('new', image), [], max_age=timedelta(minutes=6))
    with pytest.raises(ValueError):
        tentative_visual_candidate(sighting('new', image), [], min_fraction=float('nan'))


def test_unrelated_texture_is_not_a_match():
    query = sighting('new', pattern(1), seconds=10)
    assert tentative_visual_candidate(query, [sighting('old', pattern(999))]) is None


def test_future_reference_and_invalid_timestamps_rejected():
    image = pattern(4)
    assert tentative_visual_candidate(sighting('new', image), [sighting('future', image, seconds=10)]) is None
    with pytest.raises(ValueError):
        VisualSighting('A', 'cam1', 'old', datetime(2026, 10, 26), 'mug', image)


@pytest.mark.parametrize("shape", [
    (0, 100, 3), (100, 0, 3), (63, 256, 3), (256, 63, 3), (2050, 128, 3),
])
def test_malformed_bgr_crops_fail_closed_in_query_and_reference(shape):
    image = pattern(3)
    malformed = np.zeros(shape, dtype=np.uint8)
    assert tentative_visual_candidate(
        sighting('new', malformed, seconds=10), [sighting('old', image)]
    ) is None
    assert tentative_visual_candidate(
        sighting('new', image, seconds=10), [sighting('old', malformed)]
    ) is None


@pytest.mark.parametrize("other_scope", [
    {"source": "cam2"}, {"cls": "wallet"}, {"seconds": -360},
])
def test_same_tenant_duplicate_reference_id_is_ambiguous_even_outside_match_scope(other_scope):
    image = pattern(3)
    query = sighting("new", image, seconds=10)
    assert tentative_visual_candidate(query, [
        sighting("old", image), sighting("old", image, **other_scope),
    ]) is None


def test_same_tenant_query_id_replayed_from_other_camera_is_rejected():
    image = pattern(3)
    query = sighting("new", image, seconds=10)
    assert tentative_visual_candidate(query, [
        sighting("old", image), sighting("new", image, source="cam2"),
    ]) is None


def test_other_tenant_can_reuse_reference_id_without_invalidating_match():
    image = pattern(3)
    query = sighting("new", image, seconds=10)
    result = tentative_visual_candidate(query, [
        sighting("old", image), sighting("old", image, user="B"),
    ])
    assert result is not None
    assert result.reference_observation_id == "old"


def test_near_tie_below_absolute_fraction_cutoff_is_still_ambiguous(monkeypatch):
    # A competing lookalike with 19 inliers but a slightly sub-threshold
    # fraction must not disappear from the margin check against 20 inliers.
    from app.services.home_agent import visual_instance_candidate as matcher

    image = pattern(7)
    outcomes = iter([(20, 0.9), (19, 0.64)])
    monkeypatch.setattr(matcher, "_geometry", lambda *args: next(outcomes))
    assert tentative_visual_candidate(
        sighting("query", image, seconds=10),
        [sighting("reference-a", image), sighting("reference-b", image)],
    ) is None

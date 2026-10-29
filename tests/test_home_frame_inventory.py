"""Single-camera frame inventory synthetic contract; no camera or model needed."""
from dataclasses import dataclass
import pytest
from app.services.home_agent.frame_inventory import FrameInventory, describe_frame_location

@dataclass
class Box:
    label: str
    score: float
    xyxy: tuple[int, int, int, int]

@dataclass
class Track:
    observed_at: float
    box: Box
    last_detected_box: Box | None = None

def tr(t, xyxy, label="bottle"):
    return Track(t, Box(label, .8, xyxy))

def test_camera_position_is_explicitly_relative_to_frame():
    assert describe_frame_location((0, 0, 20, 20), 300, 300) == "upper-left of camera view"
    assert describe_frame_location((140, 140, 160, 160), 300, 300) == "middle-center of camera view"

def test_visible_missing_reappears_without_verified_identity():
    f = FrameInventory()
    assert [e.status for e in f.update({1: tr(1, (140, 140, 160, 160))},
                                       scan_at=1, width=300, height=300)] == ["VISIBLE"]
    assert f.update({1: tr(1, (140, 140, 160, 160))},
                    scan_at=2, width=300, height=300)[0].status == "NOT_VISIBLE"
    assert not f.visible
    assert f.update({1: tr(3, (140, 140, 160, 160))},
                    scan_at=3, width=300, height=300)[0].status == "REAPPEARED_TENTATIVE"
    assert len(f.visible) == 1

def test_near_edge_disappearance_is_possible_not_confirmed_exit():
    f = FrameInventory()
    f.update({2: tr(1, (280, 130, 300, 180))}, scan_at=1, width=300, height=300)
    events = f.update({}, scan_at=2, width=300, height=300)
    assert len(events) == 1 and events[0].status == "POSSIBLE_EXIT"
    assert events[0].last_seen_at == 1 and events[0].evidence == "detector_box_only"

def test_stale_track_is_not_currently_visible():
    f = FrameInventory()
    f.update({1: tr(1, (100, 100, 150, 150))}, scan_at=1, width=300, height=300)
    assert f.update({1: tr(1, (100, 100, 150, 150))},
                    scan_at=2, width=300, height=300)[0].status == "NOT_VISIBLE"

def test_no_duplicate_events_and_location_change():
    f = FrameInventory()
    f.update({1: tr(1, (140, 140, 160, 160))}, scan_at=1, width=300, height=300)
    assert not f.update({1: tr(2, (145, 140, 165, 160))}, scan_at=2, width=300, height=300)
    assert f.update({1: tr(3, (230, 140, 250, 160))},
                    scan_at=3, width=300, height=300)[0].status == "MOVED_IN_FRAME"


def test_clear_motion_within_same_camera_zone_is_recorded_but_jitter_is_not():
    f = FrameInventory()
    first = (120, 140, 180, 200)
    jitter = (123, 143, 183, 203)
    moved = (144, 140, 204, 200)
    assert describe_frame_location(first, 300, 300) == describe_frame_location(moved, 300, 300)
    assert [e.status for e in f.update({1: tr(1, first)},
                                       scan_at=1, width=300, height=300)] == ["VISIBLE"]
    assert f.update({1: tr(2, jitter)}, scan_at=2, width=300, height=300) == []
    events = f.update({1: tr(3, moved)}, scan_at=3, width=300, height=300)
    assert [e.status for e in events] == ["MOVED_IN_FRAME"]
    assert events[0].location == "middle-center of camera view"
    assert events[0].evidence == "detector_box_only"
    assert not f.update({1: tr(4, moved)}, scan_at=4, width=300, height=300)

def test_malformed_detection_does_not_mutate_inventory():
    f = FrameInventory()
    f.update({1: tr(1, (100, 100, 150, 150))}, scan_at=1, width=300, height=300)
    with pytest.raises(ValueError):
        f.update({2: tr(2, (500, 100, 600, 150))}, scan_at=2, width=300, height=300)
    assert 1 in f.visible and len(f.history) == 1
    assert f.update({}, scan_at=2, width=300, height=300)[0].status == "NOT_VISIBLE"

@pytest.mark.parametrize("t", [1, 0, -1, float("nan"), float("inf")])
def test_out_of_order_or_invalid_scan_rejected(t):
    f = FrameInventory()
    f.update({}, scan_at=1, width=300, height=300)
    with pytest.raises(ValueError):
        f.update({}, scan_at=t, width=300, height=300)

@pytest.mark.parametrize("dims", [(0, 300), (300, 0), (-1, 300)])
def test_invalid_frame_size_fails_even_without_detections(dims):
    with pytest.raises(ValueError):
        FrameInventory().update({}, scan_at=1, width=dims[0], height=dims[1])

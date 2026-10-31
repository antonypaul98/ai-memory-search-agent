"""Offline annotation comparison; synthetic metadata is not video acceptance."""
import hashlib
import json
from pathlib import Path

import pytest
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
from PIL import Image
from scripts.home_recorded_ground_truth import audit_ground_truth

STATES = ["VISIBLE", "CROSSING_OUT", "OUT_OF_FRAME", "CROSSING_IN", "VISIBLE"]


def _write_fixture_video(path, states):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (200, 200))
    if not writer.isOpened():
        pytest.skip("MJPG video writer unavailable")
    try:
        for state in states:
            frame = np.zeros((200, 200, 3), dtype=np.uint8)
            if state != "OUT_OF_FRAME":
                cv2.rectangle(frame, (10, 10), (50, 50), (0, 0, 255), -1)
            writer.write(frame)
    finally:
        writer.release()


def _rebind_source_digest(paths):
    digest = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    annotation = json.loads(paths[1].read_text())
    annotation["video_sha256"] = digest
    paths[1].write_text(json.dumps(annotation))
    rows = [json.loads(line) for line in paths[2].read_text().splitlines()]
    for row in rows:
        row["recorded_video"]["sha256"] = digest
    paths[2].write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def make_inputs(tmp_path, *, states=STATES, detected=None, box=None):
    video = tmp_path / "sample.avi"
    _write_fixture_video(video, states)
    annotation = tmp_path / "annotations.json"
    journal = tmp_path / "events.jsonl"
    if detected is None:
        detected = [s != "OUT_OF_FRAME" for s in states]
    samples = []
    rows = []
    for i, state in enumerate(states, 1):
        gtbox = [10, 10, 50, 50] if state != "OUT_OF_FRAME" else None
        samples.append({"scan": i, "frame_index": i - 1,
                        "state": state, "box_xyxy": gtbox})
        rows.append({"schema_version": 1, "scan_at_monotonic": i,
                     "recorded_video": {
                         "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                         "frame_index": i - 1, "sample_every": 1},
                     "events": [],
                     "visible": [{"label": "cup", "box_xyxy": box or [10, 10, 50, 50]}]
                     if detected[i - 1] else []})
    annotation.write_text(json.dumps({"schema_version": 1,
                                      "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                                      "camera_fixed": True,
                                      "manual_frame_review_completed": True,
                                      "object_label": "cup", "sample_every": 1,
                                      "samples": samples}))
    journal.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    return video, annotation, journal


def audit(paths):
    return audit_ground_truth(video_path=paths[0], annotations_path=paths[1], journal_path=paths[2])


def test_claimed_crossing_still_not_automatically_accepted(tmp_path):
    report = audit(make_inputs(tmp_path))
    assert report["reviewer_claims_frame_exit_return"] is True
    assert not report["missed_visible_scans"] and not report["unexpected_out_of_frame_detections"]
    assert report["sampled_source_frames_decoded"] is True
    assert report["automatic_demo_acceptance"] is False
    assert report["physical_identity_verified"] is False


def test_detector_miss_is_not_a_witnessed_exit(tmp_path):
    report = audit(make_inputs(tmp_path, states=["VISIBLE"] * 5,
                               detected=[True, True, False, True, True]))
    assert report["reviewer_claims_frame_exit_return"] is False
    assert report["missed_visible_scans"] == [3]


def test_unexpected_detection_when_annotated_absent(tmp_path):
    report = audit(make_inputs(tmp_path, detected=[True] * 5))
    assert report["unexpected_out_of_frame_detections"] == [3]


def test_bad_localization_reported(tmp_path):
    report = audit(make_inputs(tmp_path, box=[150, 150, 180, 180]))
    assert report["poor_localization_scans"] == [1, 2, 4, 5]


def test_long_absence_with_distinct_return_not_rejected_by_track_id(tmp_path):
    states = ["VISIBLE", "CROSSING_OUT"] + ["OUT_OF_FRAME"] * 7 + ["CROSSING_IN", "VISIBLE"]
    report = audit(make_inputs(tmp_path, states=states))
    assert report["reviewer_claims_frame_exit_return"]
    assert report["scans_compared"] == 11


def test_missing_crossing_not_claimed(tmp_path):
    report = audit(make_inputs(tmp_path, states=["VISIBLE", "OUT_OF_FRAME", "VISIBLE"]))
    assert not report["reviewer_claims_frame_exit_return"]


def test_source_must_decode_even_with_matching_digest(tmp_path):
    paths = make_inputs(tmp_path)
    paths[0].write_bytes(b"fixture-only-not-real-video")
    _rebind_source_digest(paths)
    with pytest.raises(ValueError, match="source video cannot be decoded"):
        audit(paths)


def test_source_must_contain_every_annotated_frame(tmp_path):
    paths = make_inputs(tmp_path)
    _write_fixture_video(paths[0], ["VISIBLE"])
    _rebind_source_digest(paths)
    with pytest.raises(ValueError, match="source video missing decodable annotated frame"):
        audit(paths)


def test_annotation_box_must_fit_decoded_frame(tmp_path):
    paths = make_inputs(tmp_path)
    annotation = json.loads(paths[1].read_text())
    annotation["samples"][0]["box_xyxy"] = [10, 10, 500, 500]
    paths[1].write_text(json.dumps(annotation))
    with pytest.raises(ValueError, match="annotation box exceeds decoded source frame"):
        audit(paths)


def test_mismatched_video_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    paths[0].write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        audit(paths)


def test_unrelated_journal_source_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    rows = [json.loads(x) for x in paths[2].read_text().splitlines()]
    rows[0]["recorded_video"]["sha256"] = "0" * 64
    paths[2].write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    with pytest.raises(ValueError, match="journal source video hash"):
        audit(paths)


def test_unbound_journal_source_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    rows = [json.loads(x) for x in paths[2].read_text().splitlines()]
    del rows[0]["recorded_video"]
    paths[2].write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    with pytest.raises(ValueError, match="journal source video hash"):
        audit(paths)


@pytest.mark.parametrize("field,value", [("frame_index", 999), ("sample_every", 2),
                                         ("frame_index", True)])
def test_journal_source_sampling_mismatch_rejected(tmp_path, field, value):
    paths = make_inputs(tmp_path)
    rows = [json.loads(x) for x in paths[2].read_text().splitlines()]
    rows[0]["recorded_video"][field] = value
    paths[2].write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    with pytest.raises(ValueError, match="journal source sampling"):
        audit(paths)


def test_incomplete_manual_review_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    data = json.loads(paths[1].read_text())
    data["manual_frame_review_completed"] = False
    paths[1].write_text(json.dumps(data))
    with pytest.raises(ValueError, match="manual review"):
        audit(paths)


def test_scan_alignment_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    data = json.loads(paths[1].read_text())
    data["samples"][2]["frame_index"] = 99
    paths[1].write_text(json.dumps(data))
    with pytest.raises(ValueError, match="frame index"):
        audit(paths)


def test_out_of_frame_box_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    data = json.loads(paths[1].read_text())
    data["samples"][2]["box_xyxy"] = [1, 2, 3, 4]
    paths[1].write_text(json.dumps(data))
    with pytest.raises(ValueError, match="out-of-frame"):
        audit(paths)


def test_extra_journal_scan_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    with paths[2].open("a") as f:
        f.write(json.dumps({"schema_version": 1, "scan_at_monotonic": 6, "visible": []}) + "\n")
    with pytest.raises(ValueError, match="different scan counts"):
        audit(paths)


def test_malformed_journal_box_reports_poor_localization(tmp_path):
    paths = make_inputs(tmp_path)
    rows = [json.loads(x) for x in paths[2].read_text().splitlines()]
    rows[0]["visible"][0]["box_xyxy"] = [True, 1, 50, 50]
    paths[2].write_text("\n".join(json.dumps(x) for x in rows))
    assert audit(paths)["poor_localization_scans"] == [1]


def test_missing_evidence_image_reported(tmp_path):
    paths = make_inputs(tmp_path)
    rows = [json.loads(x) for x in paths[2].read_text().splitlines()]
    rows[0]["events"] = [{"evidence_image": "events-evidence/0000-" + "a" * 32 + ".jpg"}]
    paths[2].write_text("\n".join(json.dumps(x) for x in rows))
    report = audit(paths)
    assert report["evidence_images_referenced"] == 1
    assert report["missing_evidence_image_scans"] == [1]


def test_evidence_path_traversal_rejected(tmp_path):
    paths = make_inputs(tmp_path)
    rows = [json.loads(x) for x in paths[2].read_text().splitlines()]
    rows[0]["events"] = [{"evidence_image": "../other.jpg"}]
    paths[2].write_text("\n".join(json.dumps(x) for x in rows))
    with pytest.raises(ValueError, match="unsafe evidence"):
        audit(paths)


def _add_private_crop(paths, *, corrupt=False, oversized=False):
    evidence_dir = paths[2].parent / "events-evidence"
    evidence_dir.mkdir(mode=0o700)
    name = "0000-" + "a" * 32 + ".jpg"
    image = evidence_dir / name
    if corrupt:
        image.write_bytes(b"not a decodable JPEG")
    else:
        Image.new("RGB", (321 if oversized else 16, 16), "red").save(image, format="JPEG")
    image.chmod(0o600)
    rows = [json.loads(x) for x in paths[2].read_text().splitlines()]
    rows[0]["events"] = [{"evidence_image": "events-evidence/" + name}]
    paths[2].write_text("\n".join(json.dumps(x) for x in rows) + "\n")


def test_private_evidence_pixels_decode(tmp_path):
    paths = make_inputs(tmp_path)
    _add_private_crop(paths)
    report = audit(paths)
    assert report["evidence_images_referenced"] == 1
    assert report["missing_evidence_image_scans"] == []
    assert report["invalid_evidence_image_scans"] == []


@pytest.mark.parametrize("corrupt,oversized", [(True, False), (False, True)])
def test_invalid_private_evidence_pixels_reported(tmp_path, corrupt, oversized):
    paths = make_inputs(tmp_path)
    _add_private_crop(paths, corrupt=corrupt, oversized=oversized)
    report = audit(paths)
    assert report["invalid_evidence_image_scans"] == [1]
    assert report["automatic_demo_acceptance"] is False

"""Private JPEG-to-source-frame checks; synthetic fixture is not camera acceptance."""
import hashlib
import json

import pytest
from PIL import Image

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
from scripts.home_recorded_pixel_audit import audit_event_pixels


def make_inputs(tmp_path):
    video = tmp_path / "video.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 5, (300, 180))
    if not writer.isOpened():
        pytest.skip("MJPG codec unavailable")
    for x in (10, None, 10):
        frame = np.zeros((180, 300, 3), dtype=np.uint8)
        if x is not None:
            cv2.rectangle(frame, (x, 65), (x + 65, 120), (0, 0, 255), -1)
        writer.write(frame)
    writer.release()
    capture = cv2.VideoCapture(str(video))
    ok, frame = capture.read()
    capture.release()
    assert ok
    crop = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).crop((10, 65, 76, 121))
    directory = tmp_path / "events-evidence"
    directory.mkdir(mode=0o700)
    for i in range(3):
        path = directory / (f"{i:04d}-" + "a" * 32 + ".jpg")
        crop.save(path, format="JPEG", quality=85)
        path.chmod(0o600)
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    rows = []
    for i in range(3):
        rows.append({
            "schema_version": 1,
            "recorded_video": {"sha256": digest, "frame_index": i, "sample_every": 1},
            "visible": ([{"track_id": 1, "label": "cup", "box_xyxy": [10, 65, 76, 121]}]
                        if i != 1 else []),
            "events": [{"track_id": 1, "label": "cup",
                        "status": ["VISIBLE", "NOT_VISIBLE", "REAPPEARED_TENTATIVE"][i],
                        "box_xyxy": [10, 65, 76, 121],
                        "evidence_image": f"events-evidence/{i:04d}-" + "a" * 32 + ".jpg"}],
        })
    journal = tmp_path / "events.jsonl"
    journal.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    return video, journal, directory


def rewrite(journal, rows):
    journal.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")


def test_matching_current_and_last_confirmed_crops(tmp_path):
    video, journal, _ = make_inputs(tmp_path)
    result = audit_event_pixels(video_path=video, journal_path=journal)
    assert result["pixel_matched_scans"] == [1, 2, 3]
    assert result["pixel_correspondence_complete"] is True
    assert result["automatic_demo_acceptance"] is False
    assert result["physical_camera_tested"] is False


def test_valid_but_tampered_crop_is_detected(tmp_path):
    video, journal, directory = make_inputs(tmp_path)
    path = next(directory.glob("0001*"))
    Image.new("RGB", (66, 56), "blue").save(path, format="JPEG")
    path.chmod(0o600)
    result = audit_event_pixels(video_path=video, journal_path=journal)
    assert result["pixel_mismatched_scans"] == [2]
    assert not result["pixel_correspondence_complete"]


def test_wrong_crop_dimensions_are_detected(tmp_path):
    video, journal, directory = make_inputs(tmp_path)
    path = next(directory.glob("0001*"))
    Image.new("RGB", (8, 8), "red").save(path, format="JPEG")
    path.chmod(0o600)
    assert audit_event_pixels(video_path=video, journal_path=journal)["pixel_mismatched_scans"] == [2]


def test_changed_source_hash_is_rejected(tmp_path):
    video, journal, _ = make_inputs(tmp_path)
    video.write_bytes(b"changed source")
    with pytest.raises(ValueError, match="hash"):
        audit_event_pixels(video_path=video, journal_path=journal)


def test_duplicate_crop_reference_is_rejected(tmp_path):
    video, journal, _ = make_inputs(tmp_path)
    rows = [json.loads(x) for x in journal.read_text().splitlines()]
    rows[1]["events"][0]["evidence_image"] = rows[0]["events"][0]["evidence_image"]
    rewrite(journal, rows)
    with pytest.raises(ValueError, match="duplicate"):
        audit_event_pixels(video_path=video, journal_path=journal)


def test_world_readable_crop_is_rejected(tmp_path):
    video, journal, directory = make_inputs(tmp_path)
    next(directory.glob("0001*")).chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        audit_event_pixels(video_path=video, journal_path=journal)


def test_no_crops_is_not_a_pixel_pass(tmp_path):
    video, journal, _ = make_inputs(tmp_path)
    rows = [json.loads(x) for x in journal.read_text().splitlines()]
    for row in rows:
        row["events"][0]["evidence_image"] = None
    rewrite(journal, rows)
    result = audit_event_pixels(video_path=video, journal_path=journal)
    assert not result["pixel_correspondence_complete"]


@pytest.mark.parametrize("field,value", [("box_xyxy", [15, 65, 76, 121]),
                                         ("label", "bottle")])
def test_inconsistent_event_provenance_is_unverifiable(tmp_path, field, value):
    video, journal, _ = make_inputs(tmp_path)
    rows = [json.loads(x) for x in journal.read_text().splitlines()]
    rows[1]["events"][0][field] = value
    rewrite(journal, rows)
    result = audit_event_pixels(video_path=video, journal_path=journal)
    assert result["pixel_unverifiable_scans"] == [2]
    assert not result["pixel_correspondence_complete"]


def test_changed_sampling_interval_is_rejected(tmp_path):
    video, journal, _ = make_inputs(tmp_path)
    rows = [json.loads(x) for x in journal.read_text().splitlines()]
    rows[1]["recorded_video"]["sample_every"] = 2
    rows[1]["recorded_video"]["frame_index"] = 2
    rewrite(journal, rows)
    with pytest.raises(ValueError, match="sampling interval"):
        audit_event_pixels(video_path=video, journal_path=journal)


def test_symlink_evidence_is_rejected(tmp_path):
    video, journal, directory = make_inputs(tmp_path)
    path = next(directory.glob("0001*"))
    original = tmp_path / "original.jpg"
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        audit_event_pixels(video_path=video, journal_path=journal)


def test_out_of_bounds_source_box_is_rejected(tmp_path):
    video, journal, _ = make_inputs(tmp_path)
    rows = [json.loads(x) for x in journal.read_text().splitlines()]
    rows[0]["visible"][0]["box_xyxy"] = [10, 65, 301, 121]
    rewrite(journal, rows)
    with pytest.raises(ValueError, match="outside source"):
        audit_event_pixels(video_path=video, journal_path=journal)


def test_corrupt_private_crop_fails_closed(tmp_path):
    video, journal, directory = make_inputs(tmp_path)
    path = next(directory.glob("0001*"))
    path.write_bytes(b"not a JPEG")
    path.chmod(0o600)
    with pytest.raises((OSError, ValueError)):
        audit_event_pixels(video_path=video, journal_path=journal)

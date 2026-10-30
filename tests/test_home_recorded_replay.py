"""Recorded-video pipeline regressions. Synthetic pixels are not camera acceptance."""
import hashlib
import json
from types import SimpleNamespace
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
from scripts.home_recorded_replay import replay_recorded_video, _single_track_transition_pattern


class RedObjectDetector:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = 0, fail_on

    def detect(self, image):
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("inference failed")
        rgb = np.asarray(image)
        mask = (rgb[:, :, 0] > 130) & (rgb[:, :, 1] < 90) & (rgb[:, :, 2] < 90)
        ys, xs = np.where(mask)
        if not len(xs):
            return []
        width, height = image.size
        return [SimpleNamespace(object_class="cup", confidence=.95,
                                box=(int(xs.min()) / width, int(ys.min()) / height,
                                     (int(xs.max()) + 1) / width,
                                     (int(ys.max()) + 1) / height))]


def make_video(path, positions):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (300, 180))
    if not writer.isOpened():
        pytest.skip("MJPG codec unavailable")
    try:
        for x in positions:
            frame = np.zeros((180, 300, 3), dtype=np.uint8)
            if x is not None:
                cv2.rectangle(frame, (x, 65), (x + 65, 120), (0, 0, 255), -1)
            writer.write(frame)
    finally:
        writer.release()


@pytest.mark.parametrize(
    "events,expected",
    [
        ([(1, "VISIBLE", "bottle"), (1, "MOVED_IN_FRAME", "bottle"),
          (1, "NOT_VISIBLE", "bottle"), (1, "REAPPEARED_TENTATIVE", "bottle")], True),
        ([(1, "VISIBLE", "bottle"), (1, "MOVED_IN_FRAME", "bottle"),
          (1, "POSSIBLE_EXIT", "bottle"), (1, "REAPPEARED_TENTATIVE", "bottle")], True),
        ([(1, "VISIBLE", "bottle"), (2, "MOVED_IN_FRAME", "bottle"),
          (3, "NOT_VISIBLE", "bottle"), (4, "REAPPEARED_TENTATIVE", "bottle")], False),
        ([(1, "MOVED_IN_FRAME", "bottle"), (1, "NOT_VISIBLE", "bottle"),
          (1, "REAPPEARED_TENTATIVE", "bottle"), (1, "VISIBLE", "bottle")], False),
        ([(1, "VISIBLE", "bottle"), (1, "MOVED_IN_FRAME", "bottle"),
          (1, "NOT_VISIBLE", "bottle"), (1, "REAPPEARED_TENTATIVE", "cup")], False),
        ([(1, "VISIBLE", "bottle"), (1, "NOT_VISIBLE", "bottle"),
          (1, "REAPPEARED_TENTATIVE", "bottle")], False),
    ],
)
def test_demo_pattern_requires_one_ordered_tentative_track(events, expected):
    sequence = [SimpleNamespace(track_id=tid, status=status, label=label)
                for tid, status, label in events]
    assert _single_track_transition_pattern(sequence) is expected


def test_decoded_video_tracks_location_disappearance_and_tentative_reentry(tmp_path):
    video = tmp_path / "moving-cup.avi"
    make_video(video, [10, 40, 70, 100, None, 100])
    out = tmp_path / "private"
    result = replay_recorded_video(video_path=video, output_dir=out,
                                   detector=RedObjectDetector(),
                                   max_scans=6, sample_every=1)
    rows = [json.loads(x) for x in (out / "events.jsonl").read_text().splitlines()]
    assert result["scans"] == 6 and len(rows) == 6
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    assert result["source_video_sha256"] == digest
    assert all(row["recorded_video"] == {"sha256": digest,
                                          "frame_index": i, "sample_every": 1}
               for i, row in enumerate(rows))
    assert result["recorded_video_processed"] and not result["physical_camera_tested"]
    assert not result["physical_identity_verified"]
    assert rows[0]["visible"][0]["location"].endswith("left of camera view")
    assert rows[3]["visible"][0]["location"].endswith("center of camera view")
    assert rows[4]["visible"] == []
    assert rows[4]["events"][0]["status"] == "NOT_VISIBLE"
    assert rows[5]["events"][0]["status"] == "REAPPEARED_TENTATIVE"
    assert result["complete_transition_sequence_observed"]
    assert "MOVED_IN_FRAME" in result["statuses"]
    for row in rows:
        for event in row["events"]:
            assert event["identity_verified"] is False
            assert (out / event["evidence_image"]).is_file()
    with pytest.raises(FileExistsError):
        replay_recorded_video(video_path=video, output_dir=out,
                              detector=RedObjectDetector(), max_scans=6, sample_every=1)


def test_inference_failure_does_not_invent_missing_object(tmp_path):
    video = tmp_path / "moving-cup.avi"
    make_video(video, [10, None])
    out = tmp_path / "private"
    with pytest.raises(RuntimeError, match="inference failed"):
        replay_recorded_video(video_path=video, output_dir=out,
                              detector=RedObjectDetector(fail_on=2),
                              max_scans=2, sample_every=1)
    rows = [json.loads(x) for x in (out / "events.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["events"][0]["status"] == "VISIBLE"


def test_changed_source_during_replay_fails_closed(tmp_path):
    video = tmp_path / "moving-cup.avi"
    make_video(video, [10])

    class MutatingDetector(RedObjectDetector):
        def detect(self, image):
            result = super().detect(image)
            video.write_bytes(b"source changed during detector invocation")
            return result

    with pytest.raises(RuntimeError, match="changed during replay"):
        replay_recorded_video(video_path=video, output_dir=tmp_path / "private",
                              detector=MutatingDetector(), max_scans=1,
                              sample_every=1)


def test_empty_detections_do_not_claim_demo_pass(tmp_path):
    video = tmp_path / "empty.avi"
    make_video(video, [None, None])
    result = replay_recorded_video(video_path=video, output_dir=tmp_path / "private",
                                   detector=RedObjectDetector(), max_scans=2,
                                   sample_every=1)
    assert result["scans"] == 2 and result["statuses"] == []
    assert result["complete_transition_sequence_observed"] is False


@pytest.mark.parametrize("max_scans,sample_every", [(0, 1), (121, 1), (1, 0), (1, 61), (True, 1)])
def test_invalid_limits_rejected_without_files(tmp_path, max_scans, sample_every):
    video = tmp_path / "exists.avi"
    video.write_bytes(b"dummy")
    with pytest.raises(ValueError):
        replay_recorded_video(video_path=video, output_dir=tmp_path / "private",
                              detector=RedObjectDetector(), max_scans=max_scans,
                              sample_every=sample_every)
    assert not (tmp_path / "private").exists()

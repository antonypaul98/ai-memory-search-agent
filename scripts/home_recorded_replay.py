"""Offline replay of an existing video through Home's detector and private evidence.

No camera, API or physical-identity claim. EOF and inference failure are never
converted into a witnessed exit.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _single_track_transition_pattern(events) -> bool:
    """Ordered statuses for one tentative track; never proof of physical exit."""
    stages: dict[int, tuple[str, int]] = {}
    for event in events:
        tid, label, status = event.track_id, event.label, event.status
        if status == "VISIBLE":
            stages[tid] = (label, 1)
            continue
        previous_label, stage = stages.get(tid, (None, 0))
        if previous_label != label:
            stages[tid] = (label, 0)
            continue
        if status == "MOVED_IN_FRAME" and stage == 1:
            stage = 2
        elif status in {"NOT_VISIBLE", "POSSIBLE_EXIT"} and stage == 2:
            stage = 3
        elif status == "REAPPEARED_TENTATIVE" and stage == 3:
            return True
        stages[tid] = (label, stage)
    return False


def replay_recorded_video(*, video_path: Path, output_dir: Path, detector,
                          room_name: str = "room-1", max_scans: int = 90,
                          sample_every: int = 5) -> dict:
    import cv2
    from PIL import Image
    from app.services.home_agent.frame_inventory import FrameInventory
    from app.services.home_agent.frame_event_log import PrivateFrameEventLog
    from app.services.home_agent.frame_evidence import PrivateFrameEvidenceStore
    from app.services.home_agent.live_preview import (
        normalized_to_pixels, reconcile_tracks, suppress_duplicates,
    )
    if not isinstance(video_path, Path) or not video_path.is_file():
        raise ValueError("input must be an existing local video file")
    if not isinstance(output_dir, Path) or not output_dir.name or output_dir.is_symlink():
        raise ValueError("invalid private output directory")
    if (isinstance(max_scans, bool) or not isinstance(max_scans, int)
            or not 1 <= max_scans <= 120):
        raise ValueError("max_scans must be 1..120")
    if (isinstance(sample_every, bool) or not isinstance(sample_every, int)
            or not 1 <= sample_every <= 60):
        raise ValueError("sample_every must be 1..60")
    if not isinstance(room_name, str) or not room_name.strip() or len(room_name) > 100:
        raise ValueError("invalid room name")
    source_digest = _sha256_file(video_path)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError("recorded video cannot be decoded")
    inventory = FrameInventory()
    tracks, next_id, scans, frames, statuses = {}, 1, 0, 0, set()
    try:
        output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        evidence = PrivateFrameEvidenceStore(output_dir / "events-evidence")
        with PrivateFrameEventLog(output_dir / "events.jsonl",
                                  camera_id="offline-recorded-video",
                                  room_name=room_name) as journal:
            while scans < max_scans and frames < max_scans * sample_every:
                ok, frame = capture.read()
                if not ok:
                    break  # EOF/decode failure is not a successful missing scan
                frames += 1
                if (frames - 1) % sample_every:
                    continue
                height, width = frame.shape[:2]
                if height <= 0 or width <= 0:
                    raise ValueError("invalid decoded frame")
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                # Failed inference propagates: never replace it with [].
                detections = detector.detect(image)
                boxes = suppress_duplicates([
                    box for item in detections
                    if (box := normalized_to_pixels(item, width, height)) is not None
                ])
                scan_at = float(scans + 1)  # ordered scan index, not wall/video time
                tracks, next_id = reconcile_tracks(tracks, boxes, scan_at,
                                                    next_id, max_age=4.0)
                events = inventory.update(tracks, scan_at=scan_at,
                                          width=width, height=height)
                refs = evidence.record_scan(image=image, visible=inventory.visible,
                                            events=events)
                journal.append_scan(scan_at=scan_at, visible=inventory.visible,
                                    events=events, evidence_files=refs,
                                    source_video_sha256=source_digest,
                                    source_frame_index=frames - 1,
                                    source_sample_every=sample_every)
                statuses.update(event.status for event in events)
                scans += 1
    finally:
        capture.release()
    if not scans:
        raise RuntimeError("recorded video contained no decodable sampled frames")
    if _sha256_file(video_path) != source_digest:
        raise RuntimeError("recorded video changed during replay")
    return {
        "source": "locally_supplied_recorded_video",
        "source_video_sha256": source_digest,
        "scans": scans,
        "statuses": sorted(statuses),
        "last_visible": [
            {"label": item.label, "location": item.location, "track_id": item.track_id,
             "identity_verified": False}
            for _, item in sorted(inventory.visible.items())
        ],
        "recorded_video_processed": True,
        "physical_camera_tested": False,
        "physical_identity_verified": False,
        "complete_transition_sequence_observed": _single_track_transition_pattern(inventory.history),
        "journal": str(output_dir / "events.jsonl"),
    }


def main(argv=None) -> None:
    from app.services.home_agent.live_preview import DEFAULT_LABELS
    from app.services.home_agent.owlvit_detector import LocalOwlViTDetector
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--room-name", default="room-1")
    parser.add_argument("--max-scans", type=int, default=90)
    parser.add_argument("--sample-every", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.2)
    args = parser.parse_args(argv)
    if not args.model_path.is_dir():
        parser.error("--model-path must be an existing local model directory")
    detector = LocalOwlViTDetector(str(args.model_path),
                                  labels=list(DEFAULT_LABELS), threshold=args.threshold)
    result = replay_recorded_video(video_path=args.video, output_dir=args.output_dir,
                                   detector=detector, room_name=args.room_name,
                                   max_scans=args.max_scans,
                                   sample_every=args.sample_every)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

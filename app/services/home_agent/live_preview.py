"""Opt-in, local-only Home Agent camera preview with tentative object tracking.

Run from the repository root:
python -m app.services.home_agent.live_preview --allow-camera --max-seconds 120

The display is live; detections arrive asynchronously. Track IDs are tentative,
not evidence of persistent physical identity. Video is saved only with
--record-file; annotated snapshots are saved only when S is pressed.
No network or database access is performed here (local model assets required).
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
from typing import Iterable

DEFAULT_LABELS = (
    "person", "water bottle", "cup", "glass", "mug", "phone", "laptop",
    "keyboard", "mouse", "monitor", "book", "notebook", "pen", "wallet",
    "keys", "bag", "backpack", "chair", "table", "desk", "sofa",
    "pillow", "lamp", "remote control", "headphones", "charger", "air purifier",
    "plate", "bowl", "shoe", "plant", "bottle",
)


@dataclass(frozen=True)
class PreviewBox:
    label: str
    score: float
    xyxy: tuple[int, int, int, int]


@dataclass
class Track:
    track_id: int
    box: PreviewBox
    observed_at: float
    flow_updated: bool = False
    last_detected_box: PreviewBox | None = None

    def __post_init__(self):
        if self.last_detected_box is None:
            self.last_detected_box = self.box


def display_box(track: Track, now: float, *, stale_after: float = 1.5) -> PreviewBox:
    """Render stale memory at its last detector-confirmed position, not optical flow."""
    if now - track.observed_at >= stale_after:
        return track.last_detected_box or track.box
    return track.box


def normalized_to_pixels(detection, width: int, height: int) -> PreviewBox | None:
    """Convert repository DetectedObject.box (normalized floats) to pixels."""
    if width <= 0 or height <= 0:
        raise ValueError("invalid frame dimensions")
    coords = getattr(detection, "box", None)
    try:
        if coords is None or len(coords) != 4:
            return None
    except (TypeError, ValueError):
        return None
    try:
        x1, y1, x2, y2 = [float(v) for v in coords]
    except (TypeError, ValueError):
        return None
    if not all(isfinite(v) for v in (x1, y1, x2, y2)):
        return None
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        return None
    left, top = int(x1 * width), int(y1 * height)
    right, bottom = min(width - 1, int(x2 * width)), min(height - 1, int(y2 * height))
    if right <= left or bottom <= top:
        return None
    try:
        score = float(detection.confidence)
        label = str(detection.object_class).strip()
    except (TypeError, ValueError, AttributeError):
        return None
    if not isfinite(score) or not 0 <= score <= 1 or not label:
        return None
    return PreviewBox(
        label=label,
        score=score,
        xyxy=(left, top, right, bottom),
    )


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0, right - left) * max(0, bottom - top)
    if not overlap:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (area_a + area_b - overlap)


def _association_label(label: str) -> str:
    """Conservative synonym mapping for tracking, not object classification."""
    return {"bottle": "water bottle"}.get(label, label)


def suppress_duplicates(detections: Iterable[PreviewBox]) -> list[PreviewBox]:
    """Conservative screen-space NMS; does not imply physical identity."""
    kept: list[PreviewBox] = []
    # Equal-confidence overlapping boxes must have the same winner even if
    # the detector returns them in a different order.
    for candidate in sorted(detections, key=lambda box: (
        -box.score, _association_label(box.label), box.xyxy, box.label
    )):
        if any(_iou(candidate.xyxy, prior.xyxy) >= (
            0.65 if _association_label(candidate.label) == _association_label(prior.label) else 0.85
        ) for prior in kept):
            continue
        kept.append(candidate)
    return kept



def scan_result_is_fresh(scan_at: float, now: float, *, max_age: float) -> bool:
    """Reject delayed detections before treating them as live observations."""
    return (isfinite(scan_at) and isfinite(now) and isfinite(max_age)
            and max_age > 0 and 0 <= now - scan_at <= max_age)


def reconcile_tracks(
    previous: dict[int, Track], detections: Iterable[PreviewBox],
    observed_at: float, next_id: int, *, max_age: float = 15.0,
) -> tuple[dict[int, Track], int]:
    """Order-invariant greedy association; never asserts physical identity."""
    remaining = {tid: t for tid, t in previous.items()
                 if 0 <= observed_at - t.observed_at <= max_age}
    # Deterministic association must not depend on detector output order.
    # These IDs are only tentative screen-space labels, not physical identity.
    ordered = sorted(detections, key=lambda box: (
        _association_label(box.label), box.xyxy, -box.score, box.label
    ))
    pairs: list[tuple[float, int, int]] = []
    for index, box in enumerate(ordered):
        for tid, old in remaining.items():
            if _association_label(old.box.label) != _association_label(box.label):
                continue
            score = _iou(old.box.xyxy, box.xyxy)
            if score >= 0.10:
                pairs.append((-score, tid, index))

    matches: dict[int, int] = {}
    matched_tracks: set[int] = set()
    for _, tid, index in sorted(pairs):
        if index not in matches and tid not in matched_tracks:
            matches[index] = tid
            matched_tracks.add(tid)

    output: dict[int, Track] = {}
    for index, box in enumerate(ordered):
        if index in matches:
            tid = matches[index]
            del remaining[tid]
        else:
            tid = next_id
            next_id += 1
        output[tid] = Track(tid, box, observed_at)
    # A temporarily missed detection is an unverified last-seen box, not a
    # confirmed current position. Keep it only for the bounded grace period.
    output.update(remaining)
    return output, next_id


def advance_with_optical_flow(cv2, np, previous_gray, gray, tracks: dict[int, Track],
                              *, now: float | None = None, max_flow_age: float = 1.5):
    """Shift visible boxes only when enough real image features support movement."""
    if previous_gray is None:
        return
    height, width = gray.shape
    for track in tracks.values():
        if now is not None and now - track.observed_at >= max_flow_age:
            track.flow_updated = False
            continue
        x1, y1, x2, y2 = track.box.xyxy
        if x2 - x1 < 8 or y2 - y1 < 8:
            track.flow_updated = False
            continue
        mask = np.zeros(previous_gray.shape, dtype=np.uint8)
        mask[y1:y2, x1:x2] = 255
        points = cv2.goodFeaturesToTrack(
            previous_gray, maxCorners=24, qualityLevel=0.02,
            minDistance=5, mask=mask,
        )
        if points is None or len(points) < 3:
            track.flow_updated = False
            continue
        new_points, status, _ = cv2.calcOpticalFlowPyrLK(
            previous_gray, gray, points, None,
        )
        if new_points is None or status is None:
            track.flow_updated = False
            continue
        good = status.reshape(-1).astype(bool)
        if good.sum() < 3:
            track.flow_updated = False
            continue
        delta = np.median((new_points - points).reshape(-1, 2)[good], axis=0)
        if not np.all(np.isfinite(delta)):
            track.flow_updated = False
            continue
        dx, dy = int(round(float(delta[0]))), int(round(float(delta[1])))
        if abs(dx) > width // 5 or abs(dy) > height // 5:
            track.flow_updated = False
            continue
        dx = max(-x1, min(width - 1 - x2, dx))
        dy = max(-y1, min(height - 1 - y2, dy))
        track.box = PreviewBox(track.box.label, track.box.score,
                               (x1 + dx, y1 + dy, x2 + dx, y2 + dy))
        track.flow_updated = True


def reserve_private_file(destination: Path) -> None:
    """Reserve an explicit output without overwriting files or following links."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    os.close(fd)


def save_private_snapshot(cv2, frame, destination: Path) -> bool:
    """Save a JPG only on request, privately and without replacing existing data."""
    directory = destination.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise RuntimeError("Snapshot directory must not be a symlink")
    directory.chmod(0o700)
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        return False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encoded.tobytes())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return True


def completed_scan_result(future):
    """Return a completed inference result, or None after a detector failure.

    A failed or cancelled scan must not terminate the camera preview or become
    an observation. Never include exception text in household preview output.
    """
    if not future.done():
        return None
    try:
        result = future.result()
    except Exception:
        return None
    # A successful Future is not proof that its payload is a usable scan.
    # The local detector returns (monotonic_timestamp, list[DetectedObject]).
    # Reject malformed results before the preview unpacks or iterates them.
    if not isinstance(result, tuple) or len(result) != 2:
        return None
    scan_at, raw = result
    if (isinstance(scan_at, bool) or not isinstance(scan_at, (int, float))
            or not isfinite(scan_at)):
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) > 100:
        return None
    return result


def run_demo(*, camera_index: int, model_path: Path, max_seconds: int,
             threshold: float, record_file: Path | None, labels: tuple[str, ...],
             scan_interval: float = 1.0, max_track_age: float = 4.0):
    import cv2
    import numpy as np
    from PIL import Image
    from .owlvit_detector import LocalOwlViTDetector
    from .frame_inventory import FrameInventory

    print("Loading local OWL-ViT model. This may take a moment...")
    detector = LocalOwlViTDetector(str(model_path), labels=list(labels), threshold=threshold)
    camera = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError("Camera unavailable or permission denied")
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    writer = None
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    tracks: dict[int, Track] = {}
    frame_inventory = FrameInventory()
    next_id = 1
    last_scan_at = None
    last_scan_requested = float("-inf")
    previous_gray = None
    started = monotonic()
    print("Live preview running. Press S to save an annotated local image; Q to close.")
    try:
        while monotonic() - started < max_seconds:
            ok, frame = camera.read()
            if not ok:
                print("Camera stopped returning frames")
                break
            height, width = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            now = monotonic()
            tracks = {tid: track for tid, track in tracks.items()
                      if 0 <= now - track.observed_at <= max_track_age}
            advance_with_optical_flow(cv2, np, previous_gray, gray, tracks, now=now)
            previous_gray = gray

            if future is not None and future.done():
                result = completed_scan_result(future)
                if result is None:
                    print("AI scan failed; retrying after interval", flush=True)
                else:
                    scan_at, raw = result
                    # Scores are detector scores, not calibrated probabilities.
                    if scan_result_is_fresh(scan_at, now, max_age=max_track_age):
                        boxes = [box for item in raw
                                 if (box := normalized_to_pixels(item, width, height)) is not None]
                        tracks, next_id = reconcile_tracks(tracks, suppress_duplicates(boxes),
                                                           scan_at, next_id,
                                                           max_age=max_track_age)
                        # Only successful, fresh detector scans update visibility.
                        # Optical flow and stale tracks never become current sightings.
                        for event in frame_inventory.update(
                                tracks, scan_at=scan_at, width=width, height=height):
                            print(f"Frame #{event.track_id} {event.label}: {event.status} "
                                  f"at {event.location} (detector metadata only)", flush=True)
                        last_scan_at = scan_at
                future = None
            if future is None and monotonic() - last_scan_requested >= scan_interval:
                scan_at = monotonic()
                last_scan_requested = scan_at
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                future = executor.submit(lambda t=scan_at, im=image: (t, detector.detect(im)))

            age = monotonic() - last_scan_at if last_scan_at is not None else None
            for track in tracks.values():
                x1, y1, x2, y2 = display_box(track, monotonic()).xyxy
                # Only a recent detector observation is "scan"; flow and stale
                # boxes are tentative overlays, never confirmed observations.
                track_age = monotonic() - track.observed_at
                color = (0, 220, 0) if track_age < 1.5 else (0, 180, 255)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                suffix = "stale" if track_age >= 1.5 else (
                    "flow" if track.flow_updated else "scan")
                location = frame_inventory.visible.get(track.track_id)
                location_text = f" | {location.location}" if location is not None else " | last seen"
                cv2.putText(frame, f"#{track.track_id} {track.box.label} "
                            f"{track.box.score:.2f} {suffix}{location_text}",
                            (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.50, color, 2)
            scan_text = "Scanning..." if age is None else f"Last AI scan: {age:.1f}s ago"
            cv2.putText(frame, f"Home Agent | {scan_text} | {len(frame_inventory.visible)} visible",
                        (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                        (255, 255, 255), 2)
            if writer is None and record_file is not None:
                reserve_private_file(record_file)
                try:
                    writer = cv2.VideoWriter(str(record_file),
                                             cv2.VideoWriter_fourcc(*"mp4v"), 20,
                                             (width, height))
                    if not writer.isOpened():
                        raise RuntimeError("Unable to open requested local recording file")
                except BaseException:
                    if writer is not None:
                        writer.release()
                    record_file.unlink(missing_ok=True)
                    raise
            if writer is not None:
                writer.write(frame)
            cv2.imshow("Home Agent - Live Object Preview", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("s"):
                # Explicit keypress only. Store locally, not in Git, logs or cloud.
                directory = Path.home() / "Pictures" / "HomeAgentPreview"
                destination = directory / ("home-agent-" +
                    datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jpg")
                if not save_private_snapshot(cv2, frame, destination):
                    print("Snapshot failed; no image saved", flush=True)
                else:
                    print("Local annotated snapshot:", destination, flush=True)
            if key == ord("q"):
                break
    finally:
        camera.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()
        executor.shutdown(wait=True, cancel_futures=True)



def run_demo_supervised(*, max_seconds: int, startup_grace_seconds: int = 90, **kwargs):
    """Enforce a wall-clock limit even if native model inference never returns.

    The preview and its camera are owned by a separate spawned process. A
    stalled detector can prevent ThreadPoolExecutor.shutdown(wait=True) from
    finishing inside that process; the parent must not wait indefinitely.
    Termination is a last-resort safety boundary, not normal camera acceptance.
    """
    process = get_context("spawn").Process(
        target=run_demo, kwargs=dict(max_seconds=max_seconds, **kwargs),
    )
    process.start()
    try:
        process.join(timeout=max_seconds + startup_grace_seconds)
        if process.is_alive():
            raise TimeoutError("Home Agent preview exceeded its wall-clock limit")
        if process.exitcode != 0:
            raise RuntimeError("Home Agent preview process exited unsuccessfully")
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if process.is_alive():
                raise RuntimeError("Home Agent preview worker could not be stopped")
        process.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-camera", action="store_true",
                        help="Explicitly authorize local camera processing")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--model-path", type=Path, default=Path.home() /
                        ".local/home-agent-test/models/owlvit-base-patch32")
    parser.add_argument("--max-seconds", type=int, default=120)
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--startup-grace-seconds", type=int, default=90,
                        help="Maximum extra seconds for model startup and cleanup")
    parser.add_argument("--scan-interval", type=float, default=1.0)
    parser.add_argument("--record-file", type=Path,
                        help="Optional local MP4 recording; nothing saved by default")
    parser.add_argument("--labels", nargs="+", default=DEFAULT_LABELS)
    args = parser.parse_args(argv)
    if not args.allow_camera:
        parser.error("camera processing requires --allow-camera")
    if args.camera_index < 0 or not 1 <= args.max_seconds <= 300:
        parser.error("camera-index must be >=0 and max-seconds must be 1..300")
    if not 1 <= args.startup_grace_seconds <= 180:
        parser.error("startup-grace-seconds must be 1..180")
    if not 0 < args.threshold <= 1:
        parser.error("threshold must be in (0,1]")
    if not isfinite(args.scan_interval) or not 0.2 <= args.scan_interval <= 10:
        parser.error("scan-interval must be 0.2..10 seconds")
    if not 1 <= len(set(args.labels)) <= 32:
        parser.error("this detector supports 1..32 distinct labels per scan")
    if args.record_file is not None and args.record_file.suffix.lower() != ".mp4":
        parser.error("record-file must be an explicit .mp4 path")
    run_demo_supervised(max_seconds=args.max_seconds,
                        startup_grace_seconds=args.startup_grace_seconds,
                        camera_index=args.camera_index, model_path=args.model_path,
                        threshold=args.threshold, record_file=args.record_file,
                        labels=tuple(args.labels), scan_interval=args.scan_interval)


if __name__ == "__main__":
    main()

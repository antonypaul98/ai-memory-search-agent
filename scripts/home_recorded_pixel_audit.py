"""Offline source-frame-to-private-JPEG diagnostic for recorded Home replay.

Checks pixel correspondence, not independent annotations, object identity,
physical camera behavior, or product acceptance. No images are exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

_REF = re.compile(r"events-evidence/[0-9]{4}-[0-9a-f]{32}\.jpg\Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_private_crop(path: Path) -> Image.Image:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_mode & 0o077 or not 1 <= info.st_size <= 1_000_000):
            raise ValueError("evidence file must be a bounded private regular file")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            with Image.open(stream) as image:
                if (image.format != "JPEG" or not 1 <= image.width <= 320
                        or not 1 <= image.height <= 320):
                    raise ValueError("invalid bounded JPEG evidence")
                return image.convert("RGB")
    finally:
        if fd >= 0:
            os.close(fd)


def _box(value, width: int, height: int):
    if (not isinstance(value, list) or len(value) != 4
            or any(type(x) is not int for x in value)):
        raise ValueError("invalid visible detection box")
    x1, y1, x2, y2 = value
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("visible detection box outside source frame")
    return tuple(value)


def audit_event_pixels(*, video_path: Path, journal_path: Path,
                       mean_error_limit: float = 22.0) -> dict:
    """Compare replay JPEGs to decoded source crops; diagnostic, never acceptance."""
    import cv2

    if (not isinstance(video_path, Path) or not isinstance(journal_path, Path)
            or not video_path.is_file() or not journal_path.is_file()
            or video_path.is_symlink() or journal_path.is_symlink()):
        raise ValueError("video and journal must be existing regular paths")
    if (type(mean_error_limit) not in (float, int)
            or not 0 <= mean_error_limit <= 50):
        raise ValueError("invalid pixel error limit")
    if not 0 < journal_path.stat().st_size <= 8_000_000:
        raise ValueError("journal size out of bounds")
    rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    if not 1 <= len(rows) <= 120:
        raise ValueError("expected 1..120 replay scans")
    digest = _sha256(video_path)
    if any(not isinstance(row, dict) or not isinstance(row.get("recorded_video"), dict)
           or row["recorded_video"].get("sha256") != digest for row in rows):
        raise ValueError("journal source video hash does not match")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise ValueError("source video cannot be decoded")
    previous = {}
    sample_every = None
    current_frame_index = -1
    references, matched, mismatched, unverifiable = 0, [], [], []
    used_refs = set()
    try:
        for scan, row in enumerate(rows, 1):
            if not isinstance(row, dict) or row.get("schema_version") != 1:
                raise ValueError("invalid replay journal row")
            origin = row.get("recorded_video")
            if not isinstance(origin, dict) or origin.get("sha256") != digest:
                raise ValueError("journal source video hash does not match")
            every, index = origin.get("sample_every"), origin.get("frame_index")
            if (type(every) is not int or not 1 <= every <= 60
                    or type(index) is not int or index != (scan - 1) * every
                    or index <= current_frame_index):
                raise ValueError("journal frame sampling is invalid")
            if sample_every is None:
                sample_every = every
            elif sample_every != every:
                raise ValueError("journal sampling interval changed")
            frame = None
            while current_frame_index < index:
                ok, frame = capture.read()
                current_frame_index += 1
                if not ok or frame is None:
                    raise ValueError("source video missing sampled frame")
            height, width = frame.shape[:2]
            if height <= 0 or width <= 0:
                raise ValueError("invalid source frame dimensions")
            rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            visible, events = row.get("visible"), row.get("events")
            if not isinstance(visible, list) or not isinstance(events, list):
                raise ValueError("invalid replay visibility or events")
            if any(not isinstance(s, dict) for s in visible):
                raise ValueError("invalid visible sighting")
            current = {}
            for sighting in sorted(visible, key=lambda x: x.get("track_id", -1))[:64]:
                tid, label = sighting.get("track_id"), sighting.get("label")
                if type(tid) is not int or tid < 0 or not isinstance(label, str):
                    raise ValueError("invalid visible identity metadata")
                if tid in current:
                    raise ValueError("duplicate visible track ID")
                if label.strip().lower() == "person":
                    continue
                crop = rgb.crop(_box(sighting.get("box_xyxy"), width, height))
                crop.thumbnail((320, 320))
                current[tid] = (label, crop, sighting["box_xyxy"])
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("invalid replay event")
                ref = event.get("evidence_image")
                if ref is None:
                    continue
                if not isinstance(ref, str) or not _REF.fullmatch(ref) or ref in used_refs:
                    raise ValueError("unsafe or duplicate evidence reference")
                used_refs.add(ref)
                references += 1
                status, tid, label = event.get("status"), event.get("track_id"), event.get("label")
                if type(tid) is not int or tid < 0 or not isinstance(label, str):
                    raise ValueError("invalid evidence event metadata")
                if status not in {"VISIBLE", "MOVED_IN_FRAME", "REAPPEARED_TENTATIVE",
                                  "NOT_VISIBLE", "POSSIBLE_EXIT"}:
                    raise ValueError("unknown evidence event status")
                source = previous if status in {"NOT_VISIBLE", "POSSIBLE_EXIT"} else current
                expected = source.get(tid)
                if (expected is None or expected[0] != label
                        or event.get("box_xyxy") != expected[2]
                        or label.strip().lower() == "person"):
                    unverifiable.append(scan)
                    continue
                path = journal_path.parent / ref
                if path.parent.is_symlink() or path.is_symlink():
                    raise ValueError("evidence symlinks are not accepted")
                actual = _load_private_crop(path)
                if actual.size != expected[1].size:
                    mismatched.append(scan)
                    continue
                difference = ImageChops.difference(actual, expected[1])
                error = sum(ImageStat.Stat(difference).mean) / 3
                (matched if error <= mean_error_limit else mismatched).append(scan)
            previous = current
    finally:
        capture.release()
    if _sha256(video_path) != digest:
        raise ValueError("source video changed during pixel audit")
    return {
        "source_hash_matched": True,
        "evidence_images_referenced": references,
        "pixel_matched_scans": matched,
        "pixel_mismatched_scans": mismatched,
        "pixel_unverifiable_scans": unverifiable,
        "pixel_correspondence_complete": references > 0 and not mismatched and not unverifiable,
        "automatic_demo_acceptance": False,
        "physical_identity_verified": False,
        "physical_camera_tested": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(audit_event_pixels(video_path=args.video, journal_path=args.journal), sort_keys=True))


if __name__ == "__main__":
    main()

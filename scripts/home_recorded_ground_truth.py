"""Offline comparison of reviewed fixed-camera frames with Home's replay journal.

Annotations are external claims, not independent proof of physical identity.
No camera, model, API, or evidence files are opened by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path

_STATES = {"VISIBLE", "CROSSING_OUT", "OUT_OF_FRAME", "CROSSING_IN"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CROP_REF = re.compile(r"events-evidence/[0-9]{4}-[0-9a-f]{32}\.jpg\Z")


def _box(value):
    if (not isinstance(value, list) or len(value) != 4
            or any(type(n) is not int or n < 0 for n in value)):
        raise ValueError("annotation box must be four nonnegative integers")
    if value[0] >= value[2] or value[1] >= value[3]:
        raise ValueError("annotation box must have positive area")
    return value


def _iou(a, b):
    try:
        a, b = _box(a), _box(b)
    except (TypeError, ValueError):
        return 0.0
    x = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    y = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = x * y
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection)


def audit_ground_truth(*, video_path: Path, annotations_path: Path,
                       journal_path: Path) -> dict:
    """Fail closed on mismatched sources; never infer an exit from detector misses."""
    if not all(isinstance(p, Path) and p.is_file() for p in
               (video_path, annotations_path, journal_path)):
        raise ValueError("video, annotations and journal must be existing files")
    if annotations_path.stat().st_size > 256_000 or journal_path.stat().st_size > 8_000_000:
        raise ValueError("annotation or journal exceeds bounded audit size")
    annotation = json.loads(annotations_path.read_text(encoding="utf-8"))
    if not isinstance(annotation, dict) or annotation.get("schema_version") != 1:
        raise ValueError("unsupported annotation schema")
    digest = annotation.get("video_sha256")
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise ValueError("invalid source video digest")
    hasher = hashlib.sha256()
    with video_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    if hasher.hexdigest() != digest:
        raise ValueError("annotation source video hash does not match")
    if annotation.get("camera_fixed") is not True or annotation.get("manual_frame_review_completed") is not True:
        raise ValueError("fixed-camera and completed manual review are required")
    label = annotation.get("object_label")
    if not isinstance(label, str) or not label.strip() or len(label) > 100:
        raise ValueError("invalid object label")
    sample_every = annotation.get("sample_every")
    if type(sample_every) is not int or not 1 <= sample_every <= 60:
        raise ValueError("invalid sample interval")
    samples = annotation.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 120:
        raise ValueError("expected 1..120 annotated samples")
    rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != len(samples):
        raise ValueError("journal and annotations have different scan counts")
    states, missing, unexpected, poor, missing_evidence = [], [], [], [], []
    evidence_references = 0
    for index, (sample, row) in enumerate(zip(samples, rows), 1):
        if not isinstance(sample, dict) or not isinstance(row, dict):
            raise ValueError("invalid annotation or journal row")
        state = sample.get("state")
        if (type(sample.get("scan")) is not int or sample["scan"] != index
                or state not in _STATES):
            raise ValueError("annotations must cover every scan in order")
        if (type(sample.get("frame_index")) is not int or
                sample["frame_index"] != (index - 1) * sample_every):
            raise ValueError("annotation frame index does not match replay sampling")
        box = sample.get("box_xyxy")
        if state == "OUT_OF_FRAME":
            if box is not None:
                raise ValueError("out-of-frame sample cannot have an object box")
        else:
            _box(box)
        if (row.get("schema_version") != 1 or
                type(row.get("scan_at_monotonic")) not in (int, float) or
                row["scan_at_monotonic"] != index or
                not isinstance(row.get("visible"), list) or
                not isinstance(row.get("events"), list)):
            raise ValueError("journal scan is malformed or out of order")
        matches = [s for s in row["visible"] if isinstance(s, dict) and s.get("label") == label]
        states.append(state)
        for event in row["events"]:
            if not isinstance(event, dict):
                raise ValueError("invalid journal event")
            ref = event.get("evidence_image")
            if ref is None:
                continue
            if not isinstance(ref, str) or not _CROP_REF.fullmatch(ref):
                raise ValueError("unsafe evidence image reference")
            evidence_references += 1
            evidence_dir = journal_path.parent / "events-evidence"
            image = journal_path.parent / ref
            if evidence_dir.is_symlink() or image.is_symlink():
                raise ValueError("evidence symlinks are not accepted")
            if not image.is_file():
                missing_evidence.append(index)
            elif not stat.S_ISREG(image.stat().st_mode) or image.stat().st_mode & 0o077:
                raise ValueError("evidence file is not private and regular")
        if state == "OUT_OF_FRAME":
            if matches:
                unexpected.append(index)
        elif not matches:
            missing.append(index)
        elif max((_iou(box, s.get("box_xyxy")) for s in matches), default=0) < .3:
            poor.append(index)
    pattern = ["VISIBLE", "CROSSING_OUT", "OUT_OF_FRAME", "CROSSING_IN", "VISIBLE"]
    stage = 0
    for state in states:
        if state == pattern[stage]:
            stage += 1
            if stage == len(pattern):
                break
    return {
        "source_hash_matched": True,
        "reviewer_claims_fixed_camera": True,
        "reviewer_claims_frame_exit_return": stage == len(pattern),
        "scans_compared": len(samples),
        "missed_visible_scans": missing,
        "unexpected_out_of_frame_detections": unexpected,
        "poor_localization_scans": poor,
        "evidence_images_referenced": evidence_references,
        "missing_evidence_image_scans": missing_evidence,
        "automatic_demo_acceptance": False,
        "physical_identity_verified": False,
        "physical_camera_tested": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(audit_ground_truth(video_path=args.video,
                                        annotations_path=args.annotations,
                                        journal_path=args.journal), sort_keys=True))


if __name__ == "__main__":
    main()

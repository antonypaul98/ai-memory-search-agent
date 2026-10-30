"""Opt-in CI diagnostic of *real* higher-resolution public cup-motion footage; never camera acceptance.

The fixture is not vendored or uploaded. Attribution: Pittigrilli, Wikimedia
Commons, CC BY-SA 4.0. Video is downloaded only by explicit invocation.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SOURCE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/6/6c/"
    "Ultra_slow-motion_video_of_glass_tea_cup_smashed_on_concrete_floor.webm"
)
SOURCE_PAGE = "https://commons.wikimedia.org/wiki/File:Ultra_slow-motion_video_of_glass_tea_cup_smashed_on_concrete_floor.webm"
SOURCE_LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
MODEL_REVISION = "cbc355fb364588351c5d51c7f74465e8e7ec6f72"
BOTTLE_SOURCE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/a/aa/"
    "Shake_water_sample_in_1_liter_bottle.webm"
)
BOTTLE_SOURCE_PAGE = "https://commons.wikimedia.org/wiki/File:Shake_water_sample_in_1_liter_bottle.webm"
MAX_BYTES = 4_000_000


def download_public_fixture(destination: Path, *, opener=urlopen, fixture: str = "cup") -> dict:
    """Bounded public-media download; do not follow untrusted media locations."""
    if not isinstance(destination, Path) or destination.exists() or destination.is_symlink():
        raise ValueError("fixture destination must be a new path")
    if fixture not in {"cup", "bottle"}:
        raise ValueError("unsupported public fixture")
    source_url = BOTTLE_SOURCE_URL if fixture == "bottle" else SOURCE_URL
    source_page = BOTTLE_SOURCE_PAGE if fixture == "bottle" else SOURCE_PAGE
    author = "Cirosantilli2" if fixture == "bottle" else "Pittigrilli"
    request = Request(source_url, headers={"User-Agent": "HomeAgentCIProbe/1.0 (public-media test)"})
    with opener(request, timeout=30) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or final.hostname != "upload.wikimedia.org":
            raise ValueError("unexpected public fixture host")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type not in {"video/webm", "application/octet-stream"}:
            raise ValueError("unexpected public fixture media type")
        data = response.read(MAX_BYTES + 1)
    if not 1000 <= len(data) <= MAX_BYTES:
        raise ValueError("public fixture has invalid size")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {"bytes": len(data), "sha256": sha256(data).hexdigest(),
            "source": source_page, "author": author,
            "license": SOURCE_LICENSE}



def create_public_frame_montage(video_path: Path, destination: Path, *, attribution: str = "Pittigrilli / Wikimedia Commons / CC BY-SA 4.0") -> dict:
    """Explicit public-fixture review image; never use this path for household footage."""
    import cv2
    from PIL import Image, ImageDraw
    if (not isinstance(video_path, Path) or not video_path.is_file()
            or not isinstance(destination, Path) or destination.exists()
            or destination.is_symlink()):
        raise ValueError("public montage needs a video and a new output path")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError("public review video cannot be decoded")
    indices = (0, 30, 60, 90, 120, 150, 180, 210)
    samples = []
    frame_number = 0
    try:
        while len(samples) < len(indices):
            ok, frame = capture.read()
            if not ok:
                break
            if frame_number == indices[len(samples)]:
                rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                rgb.thumbnail((240, 135))
                samples.append((frame_number, rgb))
            frame_number += 1
    finally:
        capture.release()
    if not samples:
        raise RuntimeError("public review video has no decodable frames")
    sheet = Image.new("RGB", (960, 368), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (frame_number, thumbnail) in enumerate(samples):
        left, top = (index % 4) * 240, (index // 4) * 170
        sheet.paste(thumbnail, (left, top))
        draw.text((left + 4, top + 138), f"frame {frame_number}", fill="black")
    draw.text((4, 346), attribution, fill="black")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            sheet.save(output, format="JPEG", quality=80)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {"sampled_frames": [number for number, _ in samples],
            "width": 960, "height": 368, "public_fixture_only": True}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-output", type=Path)
    parser.add_argument("--fixture", choices=("cup", "bottle"), default="cup")
    parser.add_argument("--review-only", action="store_true")
    args = parser.parse_args()
    if args.fixture == "bottle" and not args.review_only:
        parser.error("bottle candidate is frame-review-only until suitability is verified")
    if args.review_only and args.review_output is None:
        parser.error("--review-only requires --review-output")
    with TemporaryDirectory(prefix="home-public-motion-") as directory:
        root = Path(directory)
        video = root / "fixture.webm"
        provenance = download_public_fixture(video, fixture=args.fixture)
        attribution = provenance["author"] + " / Wikimedia Commons / CC BY-SA 4.0"
        review = (create_public_frame_montage(video, args.review_output,
                                               attribution=attribution)
                  if args.review_output is not None else None)
        if args.review_only:
            print(json.dumps({"fixture": provenance, "review_montage": review,
                              "manual_frame_review_completed": False,
                              "detector_run": False, "physical_camera_tested": False},
                             sort_keys=True))
            return
        from huggingface_hub import snapshot_download
        from app.services.home_agent.owlvit_detector import LocalOwlViTDetector
        from scripts.home_recorded_replay import replay_recorded_video
        model_path = snapshot_download(
            "google/owlvit-base-patch32", revision=MODEL_REVISION,
            allow_patterns=["*.json", "*.txt", "pytorch_model.bin"],
        )
        detector = LocalOwlViTDetector(model_path, labels=["a photo of a glass teacup", "a photo of a glass cup", "a photo of a drinking glass", "a photo of a cup"], threshold=0.05)
        result = replay_recorded_video(
            video_path=video, output_dir=root / "private-evidence",
            detector=detector, room_name="public-fixture-room",
            max_scans=24, sample_every=10,
        )
        rows = [json.loads(line) for line in (root / "private-evidence" / "events.jsonl").read_text().splitlines()]
        assert len(rows) == result["scans"]
        assert all(not event["identity_verified"] for row in rows for event in row["events"])
        assert all((root / "private-evidence" / event["evidence_image"]).is_file()
                   for row in rows for event in row["events"] if event["evidence_image"])
        print(json.dumps({
            "fixture": provenance, "review_montage": review, "model_revision": MODEL_REVISION,
            "detector_threshold": 0.05,
            "text_query_style": "descriptive-photo-phrase",
            "candidate": "higher-resolution 1920x1080 glass-teacup footage",
            "scans": result["scans"], "statuses": result["statuses"],
            "visible_scans": sum(bool(row["visible"]) for row in rows),
            "saved_event_crops": sum(bool(event["evidence_image"])
                                     for row in rows for event in row["events"]),
            "complete_transition_sequence_observed": result["complete_transition_sequence_observed"],
            "real_recorded_video": True, "physical_camera_tested": False,
            "manual_frame_review_completed": False,
            "interpretation": "diagnostic only; clip does not show verified exit/re-entry",
        }, sort_keys=True))
        if not any(row["visible"] for row in rows):
            raise RuntimeError("trained detector found no visible target in public video")


if __name__ == "__main__":
    main()

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
MAX_BYTES = 4_000_000


def download_public_fixture(destination: Path, *, opener=urlopen) -> dict:
    """Bounded public-media download; do not follow untrusted media locations."""
    if not isinstance(destination, Path) or destination.exists() or destination.is_symlink():
        raise ValueError("fixture destination must be a new path")
    request = Request(SOURCE_URL, headers={"User-Agent": "HomeAgentCIProbe/1.0 (public-media test)"})
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
            "source": SOURCE_PAGE, "author": "Pittigrilli",
            "license": SOURCE_LICENSE}


def main() -> None:
    from huggingface_hub import snapshot_download
    from app.services.home_agent.owlvit_detector import LocalOwlViTDetector
    from scripts.home_recorded_replay import replay_recorded_video

    with TemporaryDirectory(prefix="home-public-motion-") as directory:
        root = Path(directory)
        provenance = download_public_fixture(root / "cup.webm")
        model_path = snapshot_download(
            "google/owlvit-base-patch32", revision=MODEL_REVISION,
            allow_patterns=["*.json", "*.txt", "pytorch_model.bin"],
        )
        detector = LocalOwlViTDetector(model_path, labels=["a photo of a glass teacup", "a photo of a glass cup", "a photo of a drinking glass", "a photo of a cup"], threshold=0.05)
        result = replay_recorded_video(
            video_path=root / "cup.webm", output_dir=root / "private-evidence",
            detector=detector, room_name="public-fixture-room",
            max_scans=24, sample_every=10,
        )
        rows = [json.loads(line) for line in (root / "private-evidence" / "events.jsonl").read_text().splitlines()]
        assert len(rows) == result["scans"]
        assert all(not event["identity_verified"] for row in rows for event in row["events"])
        assert all((root / "private-evidence" / event["evidence_image"]).is_file()
                   for row in rows for event in row["events"] if event["evidence_image"])
        print(json.dumps({
            "fixture": provenance, "model_revision": MODEL_REVISION,
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

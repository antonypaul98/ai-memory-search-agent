"""Synthetic-only tests for opt-in last-detector-confirmed event image evidence."""
import json
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.home_agent.frame_evidence import PrivateFrameEvidenceStore
from app.services.home_agent.frame_event_log import PrivateFrameEventLog
from app.services.home_agent.frame_inventory import FrameInventory


def track(t, box=(10, 10, 30, 30), label="bottle"):
    return SimpleNamespace(
        observed_at=t, last_detected_box=None,
        box=SimpleNamespace(label=label, score=.9, xyxy=box),
    )


def test_last_seen_crop_uses_previous_confirmed_frame_and_reentry_is_tentative():
    with TemporaryDirectory() as root:
        parent = Path(root) / "private"
        parent.mkdir(mode=0o700)
        inventory = FrameInventory()
        evidence = PrivateFrameEvidenceStore(parent / "events-evidence")
        with PrivateFrameEventLog(parent / "events.jsonl", camera_id="cam-1",
                                  room_name="office") as journal:
            for t, color, tracks in [
                (1, "red", {1: track(1)}),
                (2, "blue", {1: track(2)}),
                (3, "red", {}),
                (4, "green", {1: track(4)}),
            ]:
                image = Image.new("RGB", (60, 60), color)
                events = inventory.update(tracks, scan_at=t, width=60, height=60)
                refs = evidence.record_scan(image=image, visible=inventory.visible,
                                            events=events)
                journal.append_scan(scan_at=t, visible=inventory.visible,
                                    events=events, evidence_files=refs)
        rows = [json.loads(line) for line in (parent / "events.jsonl").read_text().splitlines()]
        assert len(rows) == 4
        assert rows[1]["events"] == []
        assert rows[2]["visible"] == []
        assert rows[2]["events"][0]["status"] == "NOT_VISIBLE"
        missing = rows[2]["events"][0]
        assert missing["evidence_image_kind"] == "last_detector_confirmed_crop"
        last_seen = parent / missing["evidence_image"]
        assert last_seen.is_file()
        assert stat.S_IMODE(last_seen.stat().st_mode) == 0o600
        with Image.open(last_seen) as saved:
            assert saved.getpixel((5, 5))[2] > 200  # blue at t=2, not red at t=3
        assert rows[3]["events"][0]["status"] == "REAPPEARED_TENTATIVE"
        assert rows[3]["events"][0]["identity_verified"] is False
        assert (parent / rows[3]["events"][0]["evidence_image"]).exists()


def test_person_images_are_not_saved_and_cap_is_enforced():
    with TemporaryDirectory() as root:
        parent = Path(root) / "private"
        parent.mkdir(mode=0o700)
        evidence = PrivateFrameEvidenceStore(parent / "crops", max_images=1)
        image = Image.new("RGB", (60, 60), "red")
        inv = FrameInventory()
        events = inv.update({1: track(1, label="person")}, scan_at=1,
                            width=60, height=60)
        assert evidence.record_scan(image=image, visible=inv.visible, events=events) == {}
        events = inv.update({2: track(2)}, scan_at=2, width=60, height=60)
        assert evidence.record_scan(image=image, visible=inv.visible, events=events)
        events = inv.update({2: track(3, box=(30, 10, 50, 30))},
                            scan_at=3, width=60, height=60)
        assert evidence.record_scan(image=image, visible=inv.visible, events=events) == {}
        assert len(list((parent / "crops").glob("*.jpg"))) == 1


def test_public_or_existing_evidence_directory_rejected():
    with TemporaryDirectory() as root:
        public = Path(root) / "public"
        public.mkdir(mode=0o755)
        with pytest.raises(PermissionError):
            PrivateFrameEvidenceStore(public / "crops")
        private = Path(root) / "private"
        private.mkdir(mode=0o700)
        PrivateFrameEvidenceStore(private / "crops")
        with pytest.raises(FileExistsError):
            PrivateFrameEvidenceStore(private / "crops")


def test_mismatched_box_rejected_without_writing_image():
    with TemporaryDirectory() as root:
        parent = Path(root) / "private"
        parent.mkdir(mode=0o700)
        evidence = PrivateFrameEvidenceStore(parent / "crops")
        inventory = FrameInventory()
        events = inventory.update({1: track(1)}, scan_at=1, width=60, height=60)
        with pytest.raises(ValueError):
            evidence.record_scan(image=Image.new("RGB", (20, 20)),
                                 visible=inventory.visible, events=events)
        assert not list((parent / "crops").iterdir())


def test_cli_requires_explicit_event_journal_for_crops(monkeypatch, tmp_path):
    from app.services.home_agent import live_preview
    monkeypatch.setattr(live_preview, "run_demo_supervised",
                        lambda **kwargs: pytest.fail("must not open camera"))
    with pytest.raises(SystemExit):
        live_preview.main(["--allow-camera", "--save-event-crops"])


def test_cli_passes_explicit_crop_opt_in_without_opening_camera(monkeypatch, tmp_path):
    from app.services.home_agent import live_preview
    seen = {}
    monkeypatch.setattr(live_preview, "run_demo_supervised",
                        lambda **kwargs: seen.update(kwargs))
    live_preview.main(["--allow-camera", "--event-log-file",
                       str(tmp_path / "events.jsonl"), "--save-event-crops"])
    assert seen["save_event_crops"] is True
    assert not (tmp_path / "events.jsonl").exists()

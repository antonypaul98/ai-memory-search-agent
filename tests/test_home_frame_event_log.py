"""Synthetic-only, no-camera tests for opt-in single-room frame event storage."""
import json
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from app.services.home_agent.frame_event_log import PrivateFrameEventLog
from app.services.home_agent.frame_inventory import FrameInventory


def track(t, box=(130, 130, 160, 160)):
    return SimpleNamespace(observed_at=t, last_detected_box=None,
                           box=SimpleNamespace(label="bottle", score=.9, xyxy=box))


def test_visible_disappears_reappears_and_history_remains():
    with TemporaryDirectory() as root:
        p = Path(root) / "events.jsonl"
        inv = FrameInventory()
        with PrivateFrameEventLog(p, camera_id="camera-1", room_name="kitchen") as log:
            for t, tracks in [(1, {1: track(1)}), (2, {}), (3, {1: track(3)})]:
                events = inv.update(tracks, scan_at=t, width=300, height=300)
                log.append_scan(scan_at=t, visible=inv.visible, events=events)
        rows = [json.loads(line) for line in p.read_text().splitlines()]
        assert len(rows) == 3
        assert rows[0]["visible"][0]["location"] == "middle-center of camera view"
        assert rows[1]["visible"] == []
        assert rows[1]["events"][0]["status"] == "NOT_VISIBLE"
        assert rows[1]["events"][0]["evidence"] == "detector_box_only"
        assert rows[2]["events"][0]["status"] == "REAPPEARED_TENTATIVE"
        assert rows[2]["visible"][0]["identity_verified"] is False
        assert rows[0]["events"][0]["status"] == "VISIBLE"
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert rows[0]["camera_id"] == "camera-1" and rows[0]["room_name"] == "kitchen"


def test_cannot_overwrite_existing_or_symlink():
    with TemporaryDirectory() as root:
        p = Path(root) / "events.jsonl"
        p.write_text("keep")
        with pytest.raises(FileExistsError):
            PrivateFrameEventLog(p, camera_id="cam", room_name="room")
        assert p.read_text() == "keep"
        link = Path(root) / "link.jsonl"
        link.symlink_to(p)
        with pytest.raises(FileExistsError):
            PrivateFrameEventLog(link, camera_id="cam", room_name="room")
        assert p.read_text() == "keep"


def test_no_log_in_public_directory():
    with TemporaryDirectory() as root:
        p = Path(root) / "public"
        p.mkdir(mode=0o755)
        with pytest.raises(PermissionError):
            PrivateFrameEventLog(p / "events.jsonl", camera_id="cam", room_name="room")
        assert not (p / "events.jsonl").exists()


def test_reject_invalid_destination_and_metadata():
    with TemporaryDirectory() as root:
        with pytest.raises(ValueError):
            PrivateFrameEventLog(Path(root) / "events.txt", camera_id="cam", room_name="room")
        with pytest.raises(ValueError):
            PrivateFrameEventLog(Path(root) / "events.jsonl", camera_id="", room_name="room")
        assert not (Path(root) / "events.jsonl").exists()


def test_preview_cli_passes_explicit_private_log_without_camera(monkeypatch, tmp_path):
    from app.services.home_agent import live_preview
    seen = {}
    monkeypatch.setattr(live_preview, "run_demo_supervised", lambda **kwargs: seen.update(kwargs))
    path = tmp_path / "session.jsonl"
    live_preview.main(["--allow-camera", "--event-log-file", str(path),
                       "--room-name", "office"])
    assert seen["event_log_file"] == path
    assert seen["room_name"] == "office"
    assert not path.exists()


def test_preview_cli_rejects_invalid_log_extension_without_camera(monkeypatch, tmp_path):
    from app.services.home_agent import live_preview
    monkeypatch.setattr(live_preview, "run_demo_supervised",
                        lambda **kwargs: pytest.fail("must not start camera"))
    with pytest.raises(SystemExit):
        live_preview.main(["--allow-camera", "--event-log-file",
                           str(tmp_path / "events.txt")])

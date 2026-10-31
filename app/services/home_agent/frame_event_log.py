"""Opt-in, local-only metadata journal for a single camera's frame inventory.

Each successful detector scan replaces the current visible inventory in its
record; history retains earlier sightings and uncertain disappearances. No
image pixels or physical-instance identity are stored by this module.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .frame_inventory import FrameEvent, FrameSighting


class PrivateFrameEventLog:
    """Append-only private JSONL of detector-confirmed frame states."""

    def __init__(self, destination: Path, *, camera_id: str, room_name: str) -> None:
        if not isinstance(destination, Path) or destination.suffix.lower() != ".jsonl":
            raise ValueError("event log must be a .jsonl path")
        if not isinstance(camera_id, str) or not camera_id.strip() or len(camera_id) > 100:
            raise ValueError("invalid camera ID")
        if not isinstance(room_name, str) or not room_name.strip() or len(room_name) > 100:
            raise ValueError("invalid room name")
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if parent.is_symlink() or not stat.S_ISDIR(parent.stat().st_mode):
            raise PermissionError("event log parent must be a real directory")
        if parent.stat().st_mode & 0o077:
            raise PermissionError("event log directory must be private (0700)")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(destination, flags, 0o600)
        try:
            # POSIX advisory lock stays held for the journal's open lifetime.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._output = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
        except BaseException:
            os.close(fd)
            destination.unlink(missing_ok=True)
            raise
        self.camera_id = camera_id.strip()
        self.room_name = room_name.strip()

    def append_scan(self, *, scan_at: float, visible: Mapping[int, FrameSighting],
                    events: list[FrameEvent],
                    evidence_files: Mapping[tuple[int, str], str] | None = None,
                    source_video_sha256: str | None = None,
                    source_frame_index: int | None = None,
                    source_sample_every: int | None = None) -> None:
        """Persist one fresh scan. Optional video origin is not an authenticity signature."""
        if source_video_sha256 is None:
            if source_frame_index is not None or source_sample_every is not None:
                raise ValueError("video provenance fields must be supplied together")
        elif (not isinstance(source_video_sha256, str) or
              re.fullmatch(r"[0-9a-f]{64}", source_video_sha256) is None or
              type(source_frame_index) is not int or source_frame_index < 0 or
              type(source_sample_every) is not int or not 1 <= source_sample_every <= 60):
            raise ValueError("invalid recorded-video provenance")
        record = {
            "schema_version": 1,
            "camera_id": self.camera_id,
            "room_name": self.room_name,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "scan_at_monotonic": scan_at,
            "visible": [
                {"track_id": item.track_id, "label": item.label,
                 "location": item.location, "box_xyxy": list(item.xyxy),
                 "detector_score": item.confidence,
                 "identity_verified": False}
                for _, item in sorted(visible.items())
            ],
            "events": [
                {"track_id": event.track_id, "label": event.label,
                 "status": event.status, "last_known_frame_location": event.location,
                 "last_seen_monotonic": event.last_seen_at,
                 "box_xyxy": list(event.xyxy), "evidence": event.evidence,
                 "identity_verified": False,
                 "evidence_image": (evidence_files or {}).get((event.track_id, event.status)),
                 "evidence_image_kind": ("last_detector_confirmed_crop" if
                    (evidence_files or {}).get((event.track_id, event.status)) else None)}
                for event in events
            ],
        }
        if source_video_sha256 is not None:
            record["recorded_video"] = {
                "sha256": source_video_sha256,
                "frame_index": source_frame_index,
                "sample_every": source_sample_every,
            }
        self._output.write(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        self._output.flush()
        os.fsync(self._output.fileno())

    def close(self) -> None:
        self._output.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

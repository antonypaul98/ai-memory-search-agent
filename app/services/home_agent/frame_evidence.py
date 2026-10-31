"""Opt-in private crops for single-camera detector events, not identity/exit proof.

Crops come from the exact frame submitted to the detector. The last confirmed
crop is retained in bounded memory only until the next successful scan; a
missing object gets that earlier crop, never a fabricated exit image. People
are excluded from automatic crops. No network or third-party identity model.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from PIL import Image

from .frame_inventory import FrameEvent, FrameSighting


class PrivateFrameEvidenceStore:
    """Write at most 256 small private JPEG crops per opt-in preview session."""

    def __init__(self, destination: Path, *, max_images: int = 256) -> None:
        if not isinstance(destination, Path) or not destination.name:
            raise ValueError("invalid evidence directory")
        if isinstance(max_images, bool) or not isinstance(max_images, int) or not 1 <= max_images <= 256:
            raise ValueError("max_images must be 1..256")
        parent = destination.parent
        if (parent.is_symlink() or not parent.is_dir()
                or parent.stat().st_mode & 0o077):
            raise PermissionError("evidence parent must be an existing private directory")
        destination.mkdir(mode=0o700, exist_ok=False)
        if not stat.S_ISDIR(destination.stat().st_mode):
            raise PermissionError("invalid evidence directory")
        self.destination = destination
        self.max_images = max_images
        self._written = 0
        self._last_crops: dict[int, Image.Image] = {}

    def record_scan(self, *, image: Image.Image,
                    visible: Mapping[int, FrameSighting],
                    events: list[FrameEvent]) -> dict[tuple[int, str], str]:
        """Return journal-relative filenames for events with actual saved crops."""
        if not isinstance(image, Image.Image):
            raise ValueError("evidence requires its detector-submitted image")
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("invalid evidence image")
        crops: dict[int, Image.Image] = {}
        for tid, item in sorted(visible.items())[:64]:
            if item.label.strip().lower() == "person":
                continue
            x1, y1, x2, y2 = item.xyxy
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError("detector box does not match captured image")
            crop = image.crop((x1, y1, x2, y2)).convert("RGB")
            crop.thumbnail((320, 320))
            crops[tid] = crop
        saved: dict[tuple[int, str], str] = {}
        for event in events:
            if self._written >= self.max_images:
                break
            if event.label.strip().lower() == "person":
                continue
            source = (self._last_crops if event.status in
                      {"NOT_VISIBLE", "POSSIBLE_EXIT"} else crops)
            crop = source.get(event.track_id)
            if crop is None:
                continue
            name = f"{self._written:04d}-{uuid4().hex}.jpg"
            target = self.destination / name
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                with os.fdopen(fd, "wb") as output:
                    crop.save(output, format="JPEG", quality=85)
                    output.flush()
                    os.fsync(output.fileno())
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            saved[(event.track_id, event.status)] = f"{self.destination.name}/{name}"
            self._written += 1
        self._last_crops = crops
        return saved

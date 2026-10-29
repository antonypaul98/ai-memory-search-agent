"""One-camera detector-confirmed inventory; no physical-identity or room-exit claims.

A missed fresh scan means NOT_VISIBLE. A near-edge disappearance is only a
POSSIBLE_EXIT. Evidence is detector metadata, not a stored image or a witnessed
crossing. All data stays in memory in this software slice.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Mapping


@dataclass(frozen=True, slots=True)
class FrameSighting:
    track_id: int
    label: str
    location: str
    xyxy: tuple[int, int, int, int]
    confidence: float
    observed_at: float


@dataclass(frozen=True, slots=True)
class FrameEvent:
    track_id: int
    label: str
    status: str
    location: str
    observed_at: float
    last_seen_at: float
    xyxy: tuple[int, int, int, int]
    evidence: str = "detector_box_only"


def describe_frame_location(box: tuple[int, int, int, int], width: int, height: int) -> str:
    """Coarse camera coordinates, not inferred furniture or room-level position."""
    if (isinstance(width, bool) or isinstance(height, bool)
            or not isinstance(width, int) or not isinstance(height, int)
            or width <= 0 or height <= 0):
        raise ValueError("invalid frame dimensions")
    if (not isinstance(box, tuple) or len(box) != 4
            or any(isinstance(v, bool) or not isinstance(v, int) for v in box)):
        raise ValueError("invalid box")
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("box outside frame")
    x, y = (x1 + x2) / (2 * width), (y1 + y2) / (2 * height)
    horizontal = "left" if x < 1 / 3 else "right" if x >= 2 / 3 else "center"
    vertical = "upper" if y < 1 / 3 else "lower" if y >= 2 / 3 else "middle"
    return f"{vertical}-{horizontal} of camera view"


def _significant_box_motion(previous: tuple[int, int, int, int],
                            current: tuple[int, int, int, int],
                            width: int, height: int) -> bool:
    """Detect clear detector-box displacement even within one coarse zone.

    Four percent of the frame diagonal suppresses small box jitter. This is
    tentative screen-space motion, not proof of physical-instance identity.
    """
    dx = (current[0] + current[2] - previous[0] - previous[2]) / 2
    dy = (current[1] + current[3] - previous[1] - previous[3]) / 2
    return hypot(dx, dy) >= 0.04 * hypot(width, height)


class FrameInventory:
    """Per-camera current visibility and evidence metadata from successful scans.

    Track IDs are tentative session-local associations, never verified physical
    identities. A missing detection does not prove an object exited the room.
    """

    def __init__(self) -> None:
        self.visible: dict[int, FrameSighting] = {}
        self.history: list[FrameEvent] = []
        self._last_scan_at: float | None = None
        self._last_seen: dict[int, FrameSighting] = {}

    def update(self, tracks: Mapping[int, object], *, scan_at: float,
               width: int, height: int) -> list[FrameEvent]:
        if (isinstance(scan_at, bool) or not isinstance(scan_at, (int, float))
                or not isfinite(scan_at) or scan_at < 0
                or (self._last_scan_at is not None and scan_at <= self._last_scan_at)):
            raise ValueError("scan timestamp must increase")
        if (isinstance(width, bool) or isinstance(height, bool)
                or not isinstance(width, int) or not isinstance(height, int)
                or width <= 0 or height <= 0):
            raise ValueError("invalid frame dimensions")
        if not isinstance(tracks, Mapping):
            raise ValueError("tracks must be a mapping")
        fresh: dict[int, FrameSighting] = {}
        for tid, track in tracks.items():
            if isinstance(tid, bool) or not isinstance(tid, int) or tid < 0:
                raise ValueError("invalid track ID")
            at = track.observed_at
            if (isinstance(at, bool) or not isinstance(at, (int, float))
                    or not isfinite(at) or at > scan_at):
                raise ValueError("invalid track timestamp")
            if at != scan_at:
                continue
            box = track.last_detected_box or track.box
            if not isinstance(box.label, str) or not box.label.strip():
                raise ValueError("invalid detection label")
            if (isinstance(box.score, bool) or not isinstance(box.score, (int, float))
                    or not isfinite(box.score) or not 0 <= box.score <= 1):
                raise ValueError("invalid detection score")
            loc = describe_frame_location(box.xyxy, width, height)
            fresh[tid] = FrameSighting(tid, box.label, loc, box.xyxy, box.score, scan_at)
        events: list[FrameEvent] = []
        for tid, old in sorted(self.visible.items()):
            if tid not in fresh:
                x1, y1, x2, y2 = old.xyxy
                edge = (x1 <= width * .05 or y1 <= height * .05
                        or x2 >= width * .95 or y2 >= height * .95)
                status = "POSSIBLE_EXIT" if edge else "NOT_VISIBLE"
                events.append(FrameEvent(tid, old.label, status, old.location,
                                         scan_at, old.observed_at, old.xyxy))
        for tid, new in sorted(fresh.items()):
            old = self.visible.get(tid)
            if old is None:
                status = "REAPPEARED_TENTATIVE" if tid in self._last_seen else "VISIBLE"
            elif (old.location != new.location or
                  _significant_box_motion(old.xyxy, new.xyxy, width, height)):
                status = "MOVED_IN_FRAME"
            else:
                status = None
            if status:
                events.append(FrameEvent(tid, new.label, status, new.location,
                                         scan_at, scan_at, new.xyxy))
        self.visible = fresh
        self._last_seen.update(fresh)
        self._last_scan_at = scan_at
        self.history.extend(events)
        return events

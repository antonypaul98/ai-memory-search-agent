"""Regressions for actual camera-read pacing and frame timestamp provenance."""
from datetime import datetime, timedelta, timezone

from app.services.home_agent.frame_source import DeviceFrameStream


def test_camera_read_is_paced_before_timestamping_next_frame():
    events = []

    class Device:
        def __init__(self):
            self.frames = iter([b"a", b"b"])
            self.closed = False

        def open(self):
            events.append("open")

        def read(self):
            events.append("read")
            return next(self.frames, None)

        def close(self):
            events.append("close")
            self.closed = True

    def clock():
        events.append("timestamp")
        return datetime(2026, 10, 11, tzinfo=timezone.utc) + timedelta(
            seconds=events.count("timestamp") - 1
        )

    def sleeper(seconds):
        assert seconds == 1.0
        events.append("sleep")

    device = Device()
    frames = list(DeviceFrameStream(
        device=device, clock=clock, min_interval=timedelta(seconds=1),
        sleeper=sleeper,
    ))
    assert [frame.image_bytes for frame in frames] == [b"a", b"b"]
    assert events[:6] == ["open", "read", "timestamp", "sleep", "read", "timestamp"]
    assert device.closed

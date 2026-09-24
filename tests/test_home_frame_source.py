from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, call

import pytest

from app.services.home_agent.continuous_capture import CaptureRunResult
from app.services.home_agent.frame_source import ContinuousCaptureSourceAdapter, DeviceFrameStream

START = datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)


class Device:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.opened = 0
        self.closed = 0

    def open(self):
        self.opened += 1

    def read(self):
        return next(self.frames, None)

    def close(self):
        self.closed += 1


def clock(values):
    values = iter(values)
    return lambda: next(values)


def test_stream_opens_once_stamps_frames_and_closes_on_exhaustion():
    device = Device([b"a", b"b"])
    stream = DeviceFrameStream(
        device=device,
        clock=clock([START, START + timedelta(seconds=1)]),
    )
    frames = list(stream)
    assert [frame.image_bytes for frame in frames] == [b"a", b"b"]
    assert [frame.observed_at for frame in frames] == [START, START + timedelta(seconds=1)]
    assert device.opened == 1
    assert device.closed == 1
    assert stream.closed is True


def test_stream_paces_only_between_real_frames_without_delaying_initial_or_exhausted_read():
    device = Device([b"a", b"b"])
    sleeper = Mock()
    stream = DeviceFrameStream(
        device=device,
        clock=clock([START, START + timedelta(seconds=2)]),
        min_interval=timedelta(seconds=2),
        sleeper=sleeper,
    )
    frames = list(stream)
    assert [frame.image_bytes for frame in frames] == [b"a", b"b"]
    assert sleeper.call_args_list == [call(2.0)]


def test_stream_closes_when_consumer_stops_early():
    device = Device([b"a", b"b"])
    stream = DeviceFrameStream(device=device, clock=clock([START, START + timedelta(seconds=1)]))
    iterator = iter(stream)
    assert next(iterator).image_bytes == b"a"
    iterator.close()
    assert device.closed == 1
    assert stream.closed is True


def test_stream_closes_when_timestamp_is_invalid():
    device = Device([b"a"])
    stream = DeviceFrameStream(device=device, clock=lambda: datetime(2026, 9, 23, 22, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        list(stream)
    assert device.closed == 1
    assert stream.closed is True


def test_adapter_routes_device_stream_to_authenticated_runner_and_closes_source():
    runner = Mock()
    runner.run.side_effect = lambda **kwargs: (
        list(kwargs["frames"]),
        CaptureRunResult(1, (), "source_exhausted"),
    )[1]
    adapter = ContinuousCaptureSourceAdapter(runner=runner, sleeper=Mock())
    device = Device([b"image"])
    result = adapter.run_device(
        device=device, clock=clock([START]), session_id="session-1",
        user_id="tenant-a", source_id="camera-1", location="entry",
    )
    assert result.capture.frames_processed == 1
    assert result.source_closed is True
    assert device.closed == 1
    call_kwargs = runner.run.call_args.kwargs
    assert call_kwargs["session_id"] == "session-1"
    assert call_kwargs["user_id"] == "tenant-a"
    assert call_kwargs["source_id"] == "camera-1"


def test_adapter_paces_stream_with_same_interval_enforced_by_runner():
    runner = Mock()
    runner.run.side_effect = lambda **kwargs: (
        list(kwargs["frames"]),
        CaptureRunResult(2, (), "source_exhausted"),
    )[1]
    sleeper = Mock()
    adapter = ContinuousCaptureSourceAdapter(runner=runner, sleeper=sleeper)
    device = Device([b"a", b"b"])
    result = adapter.run_device(
        device=device,
        clock=clock([START, START + timedelta(seconds=3)]),
        session_id="session-1", user_id="tenant-a", source_id="camera-1", location="entry",
        min_interval=timedelta(seconds=3),
    )
    assert result.capture.frames_processed == 2
    assert runner.run.call_args.kwargs["min_interval"] == timedelta(seconds=3)
    assert sleeper.call_args_list == [call(3.0)]

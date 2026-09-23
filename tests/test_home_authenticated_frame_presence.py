from datetime import datetime, timezone
from unittest.mock import Mock

from app.services.home_agent.authenticated_frame_presence import AuthenticatedFramePresenceBridge
from app.services.home_agent.image_ingest import DetectedObject

NOW = datetime(2026, 9, 23, 13, 0, tzinfo=timezone.utc)


def detected(name: str, confidence: float) -> DetectedObject:
    return DetectedObject(name, confidence, (0.1, 0.1, 0.5, 0.8))


def test_detector_frames_are_adapted_and_sent_through_authenticated_boundary():
    authenticated = Mock()
    authenticated.ingest.return_value = None
    bridge = AuthenticatedFramePresenceBridge(presence_ingest=authenticated)

    result = bridge.ingest_frames(
        session_id="session-1",
        user_id="tenant-1",
        source_id="front-door-camera",
        frames=[
            ([detected("person", 0.91)], NOW, "frame-1"),
            ([detected("person", 0.94)], NOW, "frame-2"),
        ],
        now=NOW,
    )

    assert result is None
    call = authenticated.ingest.call_args.kwargs
    assert call["session_id"] == "session-1"
    assert call["user_id"] == "tenant-1"
    assert call["source_id"] == "front-door-camera"
    assert [item.state for item in call["observations"]] == ["home", "home"]
    assert [item.evidence_id for item in call["observations"]] == ["frame-1", "frame-2"]
    assert [item.confidence for item in call["observations"]] == [0.91, 0.94]


def test_empty_frame_is_adapted_but_authentication_is_still_delegated():
    authenticated = Mock()
    authenticated.ingest.return_value = None
    bridge = AuthenticatedFramePresenceBridge(presence_ingest=authenticated)

    bridge.ingest_frames(
        session_id="session-1",
        user_id="tenant-1",
        source_id="front-door-camera",
        frames=[([], NOW, "frame-empty")],
        now=NOW,
    )

    observation = authenticated.ingest.call_args.kwargs["observations"][0]
    assert observation.state == "away"
    assert observation.confidence == 1.0
    assert observation.source_id == "front-door-camera"
    assert observation.evidence_id == "frame-empty"

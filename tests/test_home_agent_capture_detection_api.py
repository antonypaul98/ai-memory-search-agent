"""Regressions for authenticated capture-session detection ingestion."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_capture_registry, get_home_agent_capture_service
from app.config import Settings, get_settings
from app.models.user import UserPublic
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import BoundedVisionCaptureService, CaptureSession

USER = "home-user-a"

@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    from app.main import app
    capture = MagicMock(spec=BoundedVisionCaptureService)
    registry = MagicMock(spec=CaptureSessionRegistry)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id=USER, display_name="Home User A")
    app.dependency_overrides[get_home_agent_capture_service] = lambda: capture
    app.dependency_overrides[get_home_agent_capture_registry] = lambda: registry
    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as c:
            c.capture = capture
            c.registry = registry
            yield c
    app.dependency_overrides.clear()

def _session() -> CaptureSession:
    now = datetime.now(timezone.utc)
    return CaptureSession(session_id="capture-1", user_id=USER, source_id="camera-entry", started_at=now-timedelta(seconds=10), expires_at=now+timedelta(minutes=4))

def _body() -> dict:
    return {"session_id":"capture-1","source_id":"camera-entry","object_name":"keys","location":"entry table","observed_at":datetime.now(timezone.utc).isoformat(),"confidence":0.94,"evidence_id":"frame-evidence-1"}

def test_capture_detection_is_bound_to_authenticated_session(client: TestClient) -> None:
    session = _session()
    client.registry.resolve.return_value = session
    client.capture.ingest_detection.return_value = True
    response = client.post("/api/v1/home-agent/capture-detections", json=_body())
    assert response.status_code == 200
    assert response.json() == {"stored": True}
    resolve = client.registry.resolve.call_args.kwargs
    assert resolve["session_id"] == "capture-1"
    assert resolve["user_id"] == USER
    assert resolve["source_id"] == "camera-entry"
    ingest = client.capture.ingest_detection.call_args.kwargs
    assert ingest["user_id"] == USER
    assert ingest["session"] is session
    assert ingest["detection"].object_name == "keys"
    assert ingest["consent"].user_id == USER
    assert ingest["consent"].source_id == "camera-entry"
    assert ingest["consent"].expires_at == session.expires_at

def test_capture_detection_rejects_missing_or_cross_tenant_session(client: TestClient) -> None:
    client.registry.resolve.side_effect = PermissionError("nope")
    response = client.post("/api/v1/home-agent/capture-detections", json=_body())
    assert response.status_code == 403
    client.capture.ingest_detection.assert_not_called()

def test_capture_detection_rejects_caller_supplied_user_id(client: TestClient) -> None:
    body = _body()
    body["user_id"] = "other-tenant"
    response = client.post("/api/v1/home-agent/capture-detections", json=body)
    assert response.status_code == 422
    client.registry.resolve.assert_not_called()
    client.capture.ingest_detection.assert_not_called()

"""API regressions for authenticated raw-image Home capture."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.home_image_dependencies import get_home_agent_authenticated_image_ingest
from app.config import Settings, get_settings
from app.models.user import UserPublic
from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest

USER = "home-user-a"
NOW = datetime(2026, 9, 16, 21, 30, tzinfo=timezone.utc)


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    from app.main import app
    image_ingest = MagicMock(spec=AuthenticatedHomeImageIngest)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id=USER, display_name="Home User A")
    app.dependency_overrides[get_home_agent_authenticated_image_ingest] = lambda: image_ingest
    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as c:
            c.image_ingest = image_ingest
            yield c
    app.dependency_overrides.clear()


def _url() -> str:
    query = urlencode({
        "session_id": "capture-1",
        "source_id": "camera-entry",
        "location": "entry table",
        "observed_at": NOW.isoformat(),
    })
    return f"/api/v1/home-agent/capture-images?{query}"


def test_raw_image_is_bound_to_authenticated_user_and_session(client: TestClient) -> None:
    client.image_ingest.ingest.return_value = {
        "stored": True,
        "frame_id": "frame-1",
        "detection_ms": 12.5,
        "ingestion_ms": 14.0,
    }
    response = client.post(_url(), content=b"private-image", headers={"content-type": "application/octet-stream"})
    assert response.status_code == 200
    assert response.json() == {
        "stored": True,
        "frame_id": "frame-1",
        "detection_ms": 12.5,
        "ingestion_ms": 14.0,
    }
    call = client.image_ingest.ingest.call_args.kwargs
    assert call["user_id"] == USER
    assert call["session_id"] == "capture-1"
    assert call["source_id"] == "camera-entry"
    assert call["location"] == "entry table"
    assert call["image_bytes"] == b"private-image"
    assert call["observed_at"] == NOW


def test_raw_image_rejects_cross_tenant_or_expired_session(client: TestClient) -> None:
    client.image_ingest.ingest.side_effect = PermissionError("capture session mismatch")
    response = client.post(_url(), content=b"private-image")
    assert response.status_code == 403
    assert response.json()["detail"] == "Capture session is missing, mismatched, or expired."


def test_raw_image_rejects_invalid_image_without_hiding_validation(client: TestClient) -> None:
    client.image_ingest.ingest.side_effect = ValueError("only JPEG and PNG still images are supported")
    response = client.post(_url(), content=b"not-an-image")
    assert response.status_code == 422
    assert response.json()["detail"] == "only JPEG and PNG still images are supported"

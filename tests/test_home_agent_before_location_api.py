"""HTTP acceptance for authenticated Home Agent before-location reasoning."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.config import get_settings
from app.models.user import UserPublic
from app.services.home_agent.query_service import BeforeLocationAnswer, HomeAgentQueryService


def _client(test_settings, service):
    from app.main import app
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id="owner-a", display_name="Owner A")
    app.dependency_overrides[get_home_agent_query_service] = lambda: service
    return app


def test_before_location_uses_authenticated_identity_and_preserves_evidence(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    service.before_location.return_value = BeforeLocationAnswer(
        object_name="keys", location="hall", before_location="kitchen",
        moved_at="2026-09-19T09:00:00+00:00", confidence=0.95,
        source_id="camera-kitchen", evidence_id="frame-hall",
        destination_evidence_id="frame-kitchen",
    )
    app = _client(test_settings, service)
    try:
        with patch("app.main.get_settings", lambda: test_settings):
            with TestClient(app) as client:
                response = client.post("/api/v1/home-agent/before-location", json={"object_name":"keys","location":"kitchen","min_confidence":0.8,"limit":10})
        assert response.status_code == 200
        assert response.json() == {"found":True,"text":"keys was at hall before kitchen.","object_name":"keys","location":"hall","before_location":"kitchen","moved_at":"2026-09-19T09:00:00+00:00","confidence":0.95,"source_id":"camera-kitchen","evidence_id":"frame-hall","destination_evidence_id":"frame-kitchen"}
        service.before_location.assert_called_once_with(user_id="owner-a", object_name="keys", location="kitchen", min_confidence=0.8, limit=10)
    finally:
        app.dependency_overrides.clear()


def test_before_location_rejects_caller_supplied_user_id(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    app = _client(test_settings, service)
    try:
        with patch("app.main.get_settings", lambda: test_settings):
            with TestClient(app) as client:
                response = client.post("/api/v1/home-agent/before-location", json={"object_name":"keys","location":"kitchen","user_id":"neighbor-b"})
        assert response.status_code == 422
        service.before_location.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_before_location_returns_found_false_without_transition(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    service.before_location.return_value = None
    app = _client(test_settings, service)
    try:
        with patch("app.main.get_settings", lambda: test_settings):
            with TestClient(app) as client:
                response = client.post("/api/v1/home-agent/before-location", json={"object_name":"keys","location":"garage"})
        assert response.status_code == 200
        assert response.json()["found"] is False
    finally:
        app.dependency_overrides.clear()

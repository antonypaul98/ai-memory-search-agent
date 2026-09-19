"""HTTP acceptance for authenticated Home/Jarvis natural-language physical-memory queries."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.config import get_settings
from app.models.user import UserPublic
from app.services.home_agent.query_service import BeforeLocationAnswer, HomeAgentQueryService, WhereAnswer


def _client(test_settings, service):
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id="owner-a", display_name="Owner A")
    app.dependency_overrides[get_home_agent_query_service] = lambda: service
    return app


def _post(app, test_settings, payload):
    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as client:
            return client.post("/api/v1/home-agent/query", json=payload)


def test_query_where_is_uses_authenticated_identity_and_preserves_evidence(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    service.where_is.return_value = WhereAnswer(
        object_name="keys", location="desk", observed_at="2026-09-19T12:00:00+00:00",
        confidence=0.94, source_id="camera-office", evidence_id="frame-desk",
    )
    app = _client(test_settings, service)
    try:
        response = _post(app, test_settings, {"text": "Where are my keys?", "min_confidence": 0.8})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "answered"
        assert body["kind"] == "where_is"
        assert body["location"] == "desk"
        assert body["evidence_id"] == "frame-desk"
        service.where_is.assert_called_once_with(user_id="owner-a", object_name="keys", min_confidence=0.8)
    finally:
        app.dependency_overrides.clear()


def test_query_before_location_preserves_both_evidence_ids(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    service.before_location.return_value = BeforeLocationAnswer(
        object_name="keys", location="hall", before_location="kitchen",
        moved_at="2026-09-19T09:00:00+00:00", confidence=0.95,
        source_id="camera-kitchen", evidence_id="frame-hall",
        destination_evidence_id="frame-kitchen",
    )
    app = _client(test_settings, service)
    try:
        response = _post(app, test_settings, {"text": "Where were my keys before the kitchen?", "limit": 10})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "answered"
        assert body["kind"] == "before_location"
        assert body["location"] == "hall"
        assert body["before_location"] == "kitchen"
        assert body["evidence_id"] == "frame-hall"
        assert body["destination_evidence_id"] == "frame-kitchen"
        service.before_location.assert_called_once_with(
            user_id="owner-a", object_name="keys", location="kitchen",
            min_confidence=0.5, limit=10,
        )
    finally:
        app.dependency_overrides.clear()


def test_query_unsupported_and_not_found_are_explicit(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    app = _client(test_settings, service)
    try:
        unsupported = _post(app, test_settings, {"text": "Please think about my keys"})
        assert unsupported.status_code == 200
        assert unsupported.json()["status"] == "unsupported"
        service.where_is.assert_not_called()
        service.before_location.assert_not_called()

        service.where_is.return_value = None
        missing = _post(app, test_settings, {"text": "Where are my keys?"})
        assert missing.status_code == 200
        assert missing.json()["status"] == "not_found"
        assert missing.json()["kind"] == "where_is"
    finally:
        app.dependency_overrides.clear()


def test_query_rejects_caller_supplied_tenant_identity(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    app = _client(test_settings, service)
    try:
        response = _post(app, test_settings, {"text": "Where are my keys?", "user_id": "neighbor-b"})
        assert response.status_code == 422
        service.where_is.assert_not_called()
        service.before_location.assert_not_called()
    finally:
        app.dependency_overrides.clear()

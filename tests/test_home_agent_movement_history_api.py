"""HTTP acceptance for authenticated Home Agent movement history."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.config import get_settings
from app.models.user import UserPublic
from app.services.home_agent.query_service import HomeAgentQueryService, MovementEvent


def test_movement_history_uses_authenticated_identity(test_settings) -> None:
    from app.main import app

    service = MagicMock(spec=HomeAgentQueryService)
    service.movement_history.return_value = [
        MovementEvent(
            object_name="keys",
            from_location="desk",
            to_location="kitchen",
            moved_at="2026-09-18T20:00:00+00:00",
            confidence=0.94,
            source_id="camera-kitchen",
            from_evidence_id="desk-evidence",
            to_evidence_id="kitchen-evidence",
        )
    ]
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id="owner-a", display_name="Owner A")
    app.dependency_overrides[get_home_agent_query_service] = lambda: service

    try:
        with patch("app.main.get_settings", lambda: test_settings):
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/home-agent/movement-history",
                    json={"object_name": "keys", "min_confidence": 0.8, "limit": 10},
                )
        assert response.status_code == 200
        assert response.json()["movements"] == [{
            "object_name": "keys",
            "from_location": "desk",
            "to_location": "kitchen",
            "moved_at": "2026-09-18T20:00:00+00:00",
            "confidence": 0.94,
            "source_id": "camera-kitchen",
            "from_evidence_id": "desk-evidence",
            "to_evidence_id": "kitchen-evidence",
        }]
        service.movement_history.assert_called_once_with(
            user_id="owner-a", object_name="keys", min_confidence=0.8, limit=10,
        )
    finally:
        app.dependency_overrides.clear()


def test_movement_history_rejects_caller_supplied_user_id(test_settings) -> None:
    from app.main import app

    service = MagicMock(spec=HomeAgentQueryService)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id="owner-a", display_name="Owner A")
    app.dependency_overrides[get_home_agent_query_service] = lambda: service

    try:
        with patch("app.main.get_settings", lambda: test_settings):
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/home-agent/movement-history",
                    json={"object_name": "keys", "user_id": "neighbor-b"},
                )
        assert response.status_code == 422
        service.movement_history.assert_not_called()
    finally:
        app.dependency_overrides.clear()

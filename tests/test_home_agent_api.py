"""API regression tests for authenticated Home Agent physical-memory queries."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.config import Settings, get_settings
from app.models.user import UserPublic
from app.services.home_agent.physical_memory import ObjectSighting
from app.services.home_agent.query_service import HomeAgentQueryService, WhereAnswer


AUTHENTICATED_USER_ID = "home-user-a"


def _authenticated_user() -> UserPublic:
    return UserPublic(user_id=AUTHENTICATED_USER_ID, display_name="Home User A")


@pytest.fixture
def home_agent_api_client(test_settings: Settings) -> TestClient:
    from app.main import app

    service = MagicMock(spec=HomeAgentQueryService)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = _authenticated_user
    app.dependency_overrides[get_home_agent_query_service] = lambda: service

    with patch("app.main.get_settings", lambda: test_settings):
        with TestClient(app) as client:
            client.home_agent_service = service
            yield client

    app.dependency_overrides.clear()


def test_where_is_uses_authenticated_identity(home_agent_api_client: TestClient) -> None:
    home_agent_api_client.home_agent_service.where_is.return_value = WhereAnswer(
        object_name="keys",
        location="entry table",
        observed_at="2026-09-11T06:00:00+00:00",
        confidence=0.93,
        source_id="camera-entry",
        evidence_id="evidence-1",
    )

    response = home_agent_api_client.post(
        "/api/v1/home-agent/where-is",
        json={"object_name": "keys", "min_confidence": 0.8},
    )

    assert response.status_code == 200
    assert response.json()["location"] == "entry table"
    home_agent_api_client.home_agent_service.where_is.assert_called_once_with(
        user_id=AUTHENTICATED_USER_ID,
        object_name="keys",
        min_confidence=0.8,
    )


def test_where_is_rejects_caller_supplied_user_id(home_agent_api_client: TestClient) -> None:
    response = home_agent_api_client.post(
        "/api/v1/home-agent/where-is",
        json={
            "object_name": "keys",
            "user_id": "other-tenant",
        },
    )

    assert response.status_code == 422
    home_agent_api_client.home_agent_service.where_is.assert_not_called()


def test_history_uses_authenticated_identity(home_agent_api_client: TestClient) -> None:
    home_agent_api_client.home_agent_service.history.return_value = [
        ObjectSighting(
            object_name="wallet",
            location="desk",
            observed_at=datetime(2026, 9, 11, 5, 0, tzinfo=timezone.utc),
            confidence=0.88,
            source_id="camera-office",
            evidence_id="evidence-2",
        )
    ]

    response = home_agent_api_client.post(
        "/api/v1/home-agent/history",
        json={"object_name": "wallet", "min_confidence": 0.4, "limit": 5},
    )

    assert response.status_code == 200
    assert response.json()["sightings"][0]["evidence_id"] == "evidence-2"
    home_agent_api_client.home_agent_service.history.assert_called_once_with(
        user_id=AUTHENTICATED_USER_ID,
        object_name="wallet",
        min_confidence=0.4,
        limit=5,
    )


def test_history_rejects_caller_supplied_user_id(home_agent_api_client: TestClient) -> None:
    response = home_agent_api_client.post(
        "/api/v1/home-agent/history",
        json={"object_name": "wallet", "user_id": "other-tenant"},
    )

    assert response.status_code == 422
    home_agent_api_client.home_agent_service.history.assert_not_called()

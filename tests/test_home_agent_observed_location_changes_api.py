"""Authenticated HTTP acceptance for identity-evidenced observed location changes.

No real camera, household faces, or inferred mover is involved.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.config import get_settings
from app.models.user import UserPublic
from app.services.home_agent.instance_location import ObservedLocationChange
from app.services.home_agent.query_service import HomeAgentQueryService


BASE = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)


def _post(test_settings, service, payload):
    from app.main import app
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id="house-a")
    app.dependency_overrides[get_home_agent_query_service] = lambda: service
    try:
        with patch("app.main.get_settings", lambda: test_settings):
            with TestClient(app) as client:
                return client.post("/api/v1/home-agent/observed-location-changes", json=payload)
    finally:
        app.dependency_overrides.clear()


def test_verified_change_is_tenant_bound_and_keeps_both_provenances(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    service.observed_location_changes.return_value = [ObservedLocationChange(
        user_id="house-a", instance_id="keys-1", object_class="keys",
        from_location="desk", to_location="kitchen",
        last_seen_from=BASE, first_seen_to=BASE + timedelta(seconds=30),
        from_evidence_id="frame-a", to_evidence_id="frame-b",
        from_identity_evidence_id="match-a", to_identity_evidence_id="match-b",
    )]
    response = _post(test_settings, service, {
        "object_name": "keys", "min_confidence": 0.95, "limit": 10,
    })
    assert response.status_code == 200
    assert response.json() == {"changes": [{
        "instance_id": "keys-1", "object_class": "keys",
        "from_location": "desk", "to_location": "kitchen",
        "last_seen_from": "2026-10-25T18:00:00Z",
        "first_seen_to": "2026-10-25T18:00:30Z",
        "from_evidence_id": "frame-a", "to_evidence_id": "frame-b",
        "from_identity_evidence_id": "match-a",
        "to_identity_evidence_id": "match-b",
    }]}
    service.observed_location_changes.assert_called_once_with(
        user_id="house-a", object_name="keys", min_confidence=0.95, limit=10,
    )


def test_class_only_or_unverified_memory_has_no_changes(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    service.observed_location_changes.return_value = []
    response = _post(test_settings, service, {"object_name": "keys"})
    assert response.status_code == 200
    assert response.json() == {"changes": []}
    service.observed_location_changes.assert_called_once_with(
        user_id="house-a", object_name="keys", min_confidence=0.9, limit=20,
    )


def test_rejects_caller_supplied_tenant_and_invalid_bounds(test_settings):
    service = MagicMock(spec=HomeAgentQueryService)
    for payload in (
        {"object_name": "keys", "user_id": "house-b"},
        {"object_name": "keys", "min_confidence": 1.5},
        {"object_name": "keys", "limit": 101},
    ):
        response = _post(test_settings, service, payload)
        assert response.status_code == 422
    service.observed_location_changes.assert_not_called()

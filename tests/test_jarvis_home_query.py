"""J05 software slice: authenticated, evidence-bearing physical-memory ingress."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_home_agent_query_service
from app.api.routes.jarvis import router
from app.models.user import UserPublic
from app.services.home_agent.physical_memory import ObjectSighting
from app.services.home_agent.query_service import HomeAgentQueryService, WhereAnswer


def client_for(service, user_id="owner-a"):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id=user_id)
    app.dependency_overrides[get_home_agent_query_service] = lambda: service
    return TestClient(app)


def test_home_preserves_inspectable_evidence_without_digital_runtime():
    service = MagicMock(spec=HomeAgentQueryService)
    service.where_is.return_value = WhereAnswer(
        "keys", "desk", "2026-10-04T10:00:00+00:00", .9, "camera-1", "observation-1",
        "frame-1", "sha256-1", "detector-1",
    )
    with client_for(service) as client, patch("app.api.routes.jarvis.JarvisCoreRuntime") as runtime:
        result = client.post("/jarvis/home", json={"text": "Where are my keys?", "min_confidence": .8})
    assert result.status_code == 200
    assert result.json()["evidence_frame_id"] == "frame-1"
    assert result.json()["evidence_image_sha256"] == "sha256-1"
    assert result.json()["evidence_detector_id"] == "detector-1"
    assert result.json()["evidence_id"] == "observation-1"
    service.where_is.assert_called_once_with(user_id="owner-a", object_name="keys", min_confidence=.8)
    runtime.assert_not_called()


@pytest.mark.parametrize("extra", [{"user_id": "other"}, {"timezone_name": "UTC"}, {"limit": 101}, {"min_confidence": 1.1}, {"text": " "}, {"text": "x" * 1001}])
def test_home_rejects_untrusted_identity_and_unbounded_requests(extra):
    service = MagicMock(spec=HomeAgentQueryService)
    with client_for(service) as client:
        response = client.post("/jarvis/home", json={"text": "Where are my keys?", **extra})
    assert response.status_code == 422
    assert service.mock_calls == []


def test_home_requires_authenticated_user():
    service = MagicMock(spec=HomeAgentQueryService)
    client = client_for(service)
    def reject():
        raise HTTPException(status_code=401, detail="Authentication required")
    client.app.dependency_overrides[get_current_user] = reject
    with client:
        assert client.post("/jarvis/home", json={"text": "Where are my keys?"}).status_code == 401
    assert service.mock_calls == []


def test_unsupported_write_and_missing_memory_never_fabricate_answers():
    service = MagicMock(spec=HomeAgentQueryService)
    service.where_is.return_value = None
    with client_for(service) as client:
        assert client.post("/jarvis/home", json={"text": "start camera"}).json()["status"] == "unsupported"
        assert service.mock_calls == []
        missing = client.post("/jarvis/home", json={"text": "Where are my keys?"}).json()
    assert missing["status"] == "not_found"
    assert missing["evidence_id"] is None


def test_yesterday_uses_single_sighting_and_cannot_read_other_tenant():
    yesterday = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    sighting = ObjectSighting(object_name="keys", location="desk", observed_at=yesterday,
                             confidence=.9, source_id="camera", evidence_id="e1")
    class Store:
        def history(self, *, user_id, **kwargs):
            return [sighting] if user_id == "owner-a" else []
    service = HomeAgentQueryService(Store())
    bounds = (yesterday.replace(hour=0), yesterday.replace(hour=0) + timedelta(days=1))
    with client_for(service) as client, patch("app.services.home_agent.natural_language_query._local_day_bounds", return_value=bounds):
        response = client.post("/jarvis/home", json={"text": "Where were my keys yesterday?"})
    assert response.status_code == 200
    assert response.json()["location"] == "desk"
    assert response.json()["evidence_id"] == "e1"
    with client_for(service, "other") as client, patch("app.services.home_agent.natural_language_query._local_day_bounds", return_value=bounds):
        missing = client.post("/jarvis/home", json={"text": "Where were my keys yesterday?"})
    assert missing.json()["status"] == "not_found"

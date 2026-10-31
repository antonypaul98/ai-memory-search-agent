"""Production capture dependency and structured-route wiring; synthetic, no camera."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.api import dependencies as deps
from app.api import home_image_dependencies as image_deps
from app.api.routes.home_agent import CaptureDetectionRequest, ingest_capture_detection
from app.models.user import UserPublic
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import BoundedVisionCaptureService, CaptureSession
from app.services.home_agent.postgres_capture_registry import PostgresCaptureSessionRegistry


def test_shared_capture_dependency_fails_closed_without_postgres_configuration():
    with patch.object(deps, "get_settings", return_value=object()), patch.object(
        deps, "get_postgres_connection_factory", side_effect=RuntimeError("missing DB")
    ):
        with pytest.raises(RuntimeError, match="missing DB"):
            deps.get_home_agent_capture_registry()


def test_structured_capture_dependency_uses_guarded_store_and_shared_registry():
    factory = MagicMock(name="connection_factory")
    with patch.object(deps, "get_settings", return_value=object()), patch.object(
        deps, "get_postgres_connection_factory", return_value=factory
    ), patch.object(deps, "PostgresCaptureSessionRegistry") as registry_class, patch.object(
        deps, "PostgresHomeImageStore"
    ) as store_class:
        service = deps.get_home_agent_capture_service()
    registry_class.assert_called_once_with(factory)
    store_class.assert_called_once_with(
        factory, capture_registry=registry_class.return_value
    )
    assert isinstance(service, BoundedVisionCaptureService)
    assert service._adapter._ingest_service._store is store_class.return_value


def test_image_capture_dependency_uses_same_registry_as_guarded_writer():
    factory = MagicMock(name="connection_factory")
    with patch.object(image_deps, "get_settings", return_value=object()), patch.object(
        image_deps, "get_postgres_connection_factory", return_value=factory
    ), patch.object(image_deps, "get_home_agent_capture_registry") as registry_provider, patch.object(
        image_deps, "PostgresHomeImageStore"
    ) as store_class, patch.object(image_deps, "LocalOwlViTDetector"):
        service = image_deps.get_home_agent_authenticated_image_ingest()
    store_class.assert_called_once_with(
        factory, capture_registry=registry_provider.return_value
    )
    assert service._registry is registry_provider.return_value
    assert service._image_ingest._store is store_class.return_value


@pytest.mark.parametrize("shared", [True, False])
def test_structured_capture_route_propagates_id_only_for_guarded_registry(shared):
    now = datetime.now(timezone.utc)
    session = CaptureSession(
        session_id="opaque-server-id", user_id="tenant-a", source_id="camera-1",
        started_at=now - timedelta(seconds=10),
        expires_at=now + timedelta(minutes=2),
    )
    registry = MagicMock(spec=PostgresCaptureSessionRegistry if shared else CaptureSessionRegistry)
    registry.resolve.return_value = session
    service = MagicMock(spec=BoundedVisionCaptureService)
    service.ingest_detection.return_value = True
    body = CaptureDetectionRequest(
        session_id=session.session_id, source_id=session.source_id,
        object_name="wallet", location="desk", observed_at=now,
        confidence=0.9, evidence_id="frame-1",
    )
    response = ingest_capture_detection(
        body, service=service, registry=registry,
        user=UserPublic(user_id="tenant-a", display_name="A"),
    )
    assert response.stored is True
    kwargs = service.ingest_detection.call_args.kwargs
    assert kwargs["user_id"] == "tenant-a"
    assert kwargs["session"] is session
    assert kwargs["detection"].source_id == "camera-1"
    if shared:
        assert kwargs["capture_session_id"] == session.session_id
    else:
        assert "capture_session_id" not in kwargs

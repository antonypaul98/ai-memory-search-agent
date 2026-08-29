"""Phase 4 Capture Triage Agent regression tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.capture_triage import CaptureTriageRequest
from app.services.capture_triage_agent import CaptureTriageAgent
from app.services.cross_duplicate_service import CrossConnectorDuplicateDetector


def test_canonical_duplicate_is_kept_once(test_settings: Settings) -> None:
    request = CaptureTriageRequest(
        items=[
            {"url": "https://youtu.be/dQw4w9WgXcQ"},
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=20"},
        ]
    )
    agent = CaptureTriageAgent(test_settings)
    out = agent.triage(user_id="user-a", request=request)
    assert out.ready == 1
    assert out.duplicates == 1
    assert out.rejected == 0
    assert out.decisions[0].decision == "ready"
    assert out.decisions[1].decision == "duplicate"
    assert out.decisions[1].duplicate_of_index == 0
    assert out.decisions[0].canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    ready_items = agent.ready_items(request, out)
    assert len(ready_items) == 1
    assert ready_items[0].url == "https://youtu.be/dQw4w9WgXcQ"


def test_rejects_unsupported_or_unsafe_url(test_settings: Settings) -> None:
    request = CaptureTriageRequest(items=[{"url": "chrome://settings/privacy"}])
    out = CaptureTriageAgent(test_settings).triage(user_id="user-a", request=request)
    assert out.ready == 0
    assert out.rejected == 1
    assert out.decisions[0].decision == "rejected"
    assert "unsafe" in out.decisions[0].reason.lower() or "unsupported" in out.decisions[0].reason.lower()


def test_existing_memory_duplicate_is_tenant_scoped(test_settings: Settings) -> None:
    detector = CrossConnectorDuplicateDetector(test_settings)
    detector.register(
        user_id="user-a",
        canonical_url="https://example.com/article",
        content_hash="",
        source_type="web",
        connector_id="web.v1",
        external_id="existing",
        memory_id="memory-a",
    )
    request = CaptureTriageRequest(items=[{"url": "https://example.com/article"}])

    mine = CaptureTriageAgent(test_settings).triage(user_id="user-a", request=request)
    other = CaptureTriageAgent(test_settings).triage(user_id="user-b", request=request)
    assert mine.decisions[0].decision == "duplicate"
    assert other.decisions[0].decision == "ready"


def test_triage_api_uses_authenticated_user(client: TestClient, test_settings: Settings) -> None:
    detector = CrossConnectorDuplicateDetector(test_settings)
    detector.register(
        user_id="other",
        canonical_url="https://example.com/private",
        content_hash="",
        source_type="web",
        connector_id="web.v1",
        external_id="other-memory",
    )
    response = client.post(
        "/api/v1/agents/capture/triage",
        json={"items": [{"url": "https://example.com/private"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] == 1
    assert body["decisions"][0]["decision"] == "ready"

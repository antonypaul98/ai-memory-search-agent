"""Static regression checks for the read-only agent activity workspace surface."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_activity_route_and_navigation_are_wired() -> None:
    router = _read("app/static/js/router.js")
    app = _read("app/static/app.js")
    html = _read("app/static/index.html")

    assert '"activity"' in router
    assert 'data-route="activity"' in html
    assert 'id="view-activity"' in html
    assert 'mountActivity' in app
    assert 'route === "activity"' in app


def test_activity_uses_tenant_scoped_events_api_surface() -> None:
    api = _read("app/static/js/api.js")
    view = _read("app/static/js/views/activity.js")

    assert 'apiFetch(`/events?${q}`' in api
    assert 'q.set("event_type", eventType)' in api
    assert 'Api.events(eventType' in view
    assert 'startsWith("agent.")' in view
    assert 'cache: false' in view


def test_activity_does_not_dump_arbitrary_event_payload() -> None:
    view = _read("app/static/js/views/activity.js")

    # The audit UI deliberately allowlists a small set of operational fields so
    # future event payloads cannot accidentally expose memory content or secrets.
    assert 'SAFE_PAYLOAD_KEYS' in view
    for key in ("tool", "policy_tier", "error_type", "status", "reason"):
        assert f'"{key}"' in view
    assert "JSON.stringify(event.payload" not in view
    assert "Object.entries(event.payload" not in view

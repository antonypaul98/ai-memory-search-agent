"""Offline replay ownership must be checked again at the authenticated write."""
from fastapi.testclient import TestClient
from app.main import app
from app.api.auth import get_current_user
from app.api.routes import capture
from app.models.user import UserPublic
from app.models.capture import CaptureStatusResponse


def test_cookie_account_switch_rejects_offline_replay_before_service_write(monkeypatch):
    calls = []

    class Service:
        def capture_url(self, body, *, user_id):
            calls.append((body.url, user_id))
            return CaptureStatusResponse(capture_id='test', status='queued', url=body.url)

    monkeypatch.setattr(capture, 'CaptureService', Service)
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id='tenant-b', display_name='B')
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post('/api/v1/capture/url', json={'url': 'https://example.test/a'}, headers={'X-Capture-Owner': 'tenant-a'})
        assert response.status_code == 409
        assert calls == []
        accepted = client.post('/api/v1/capture/url', json={'url': 'https://example.test/b'}, headers={'X-Capture-Owner': 'tenant-b'})
        assert accepted.status_code == 200
        assert calls == [('https://example.test/b', 'tenant-b')]
    finally:
        app.dependency_overrides.clear()

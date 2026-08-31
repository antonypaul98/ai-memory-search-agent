from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "app" / "static" / "js" / "offline_capture.js"
APP = ROOT / "app" / "static" / "app.js"


def test_offline_queue_is_wired_into_workspace():
    app = APP.read_text(encoding="utf-8")
    assert 'import { installOfflineCaptureQueue } from "./js/offline_capture.js";' in app
    assert "installOfflineCaptureQueue();" in app


def test_offline_queue_reuses_canonical_capture_endpoint_and_syncs_on_reconnect():
    source = OFFLINE.read_text(encoding="utf-8")
    assert 'fetch("/api/v1/capture/url"' in source
    assert 'window.addEventListener("online"' in source
    assert "flushOfflineCaptures" in source
    assert "removeQueued(item.id)" in source


def test_offline_queue_does_not_persist_authentication_secrets():
    source = OFFLINE.read_text(encoding="utf-8")
    add_start = source.index("store.add({")
    add_end = source.index("});", add_start)
    persisted_record = source[add_start:add_end]
    assert "url:" in persisted_record
    assert "queued_at:" in persisted_record
    assert "token" not in persisted_record.lower()
    assert "authorization" not in persisted_record.lower()
    assert 'localStorage.getItem("am_token")' in source


def test_offline_queue_is_bounded_and_http_only():
    source = OFFLINE.read_text(encoding="utf-8")
    assert "const MAX_QUEUED = 100;" in source
    assert 'if (!/^https?:$/.test(normalized.protocol))' in source
    assert "Offline queue is full" in source


def test_failed_replay_preserves_item_instead_of_dropping_it():
    source = OFFLINE.read_text(encoding="utf-8")
    response_guard = source.index("if (!response.ok)")
    delete_call = source.index("await removeQueued(item.id)")
    assert response_guard < delete_call
    assert "break;" in source[response_guard:delete_call]

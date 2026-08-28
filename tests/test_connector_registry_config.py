import pytest

from app.config import get_settings
from app.core.exceptions import AppError
from app.services.sources import get_connector_registry, reset_connector_registry_cache


def _reload_registry(monkeypatch: pytest.MonkeyPatch, enabled_ids: str):
    monkeypatch.setenv("CONNECTOR_ENABLED_IDS", enabled_ids)
    get_settings.cache_clear()
    reset_connector_registry_cache()
    return get_connector_registry()


def test_connector_registry_defaults_to_all_builtins(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _reload_registry(monkeypatch, "")

    assert registry.list_connectors() == [
        "bookmarks.v1",
        "gdrive.v1",
        "github.v1",
        "notion.v1",
        "pdf.v1",
        "podcast.v1",
        "readwise.v1",
        "web.v1",
        "youtube.v1",
    ]


def test_connector_registry_respects_configured_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _reload_registry(monkeypatch, " youtube.v1, web.v1 ")

    assert registry.list_connectors() == ["web.v1", "youtube.v1"]
    assert registry.get("youtube.v1").connector_id == "youtube.v1"
    with pytest.raises(AppError, match="Unknown connector: github.v1"):
        registry.get("github.v1")


def test_connector_registry_rejects_unknown_configured_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONNECTOR_ENABLED_IDS", "youtube.v1,typo.v1")
    get_settings.cache_clear()
    reset_connector_registry_cache()

    with pytest.raises(AppError, match=r"Unknown configured connector\(s\): typo.v1"):
        get_connector_registry()


def test_disabled_general_connector_does_not_capture_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _reload_registry(monkeypatch, "youtube.v1")

    with pytest.raises(AppError, match="No connector supports this URL"):
        registry.resolve_for_url("https://example.com/article")

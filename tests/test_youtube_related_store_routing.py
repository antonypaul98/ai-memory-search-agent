from __future__ import annotations

from app.config import Settings
from app.services.youtube_related_service import YouTubeRelatedService


class _SentinelRepository:
    pass


class _SentinelGraph:
    pass


def test_related_service_uses_selected_youtube_store(monkeypatch, tmp_path) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "memory.db"),
        youtube_store_backend="postgres",
    )
    selected_store = object()
    seen = []

    monkeypatch.setattr(
        "app.services.youtube_related_service.get_youtube_memory_store",
        lambda selected: seen.append(selected) or selected_store,
    )

    service = YouTubeRelatedService(
        settings=settings,
        repository=_SentinelRepository(),
        graph=_SentinelGraph(),
    )

    assert service._store is selected_store
    assert seen == [settings]
    assert not (tmp_path / "memory.db").exists()


def test_related_service_preserves_explicit_store_injection(monkeypatch, tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "memory.db"))
    injected_store = object()

    def fail_if_selected(_settings):
        raise AssertionError("selector must not run when a store is explicitly injected")

    monkeypatch.setattr(
        "app.services.youtube_related_service.get_youtube_memory_store",
        fail_if_selected,
    )

    service = YouTubeRelatedService(
        settings=settings,
        store=injected_store,
        repository=_SentinelRepository(),
        graph=_SentinelGraph(),
    )

    assert service._store is injected_store

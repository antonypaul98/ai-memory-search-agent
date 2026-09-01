from __future__ import annotations

from app.config import Settings
from app.services.youtube_duplicate_service import YouTubeDuplicateDetector


def test_duplicate_detector_uses_selected_youtube_store(monkeypatch, tmp_path) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "memory.db"),
        youtube_store_backend="postgres",
    )
    selected_store = object()
    seen = []

    monkeypatch.setattr(
        "app.services.youtube_duplicate_service.get_youtube_memory_store",
        lambda selected: seen.append(selected) or selected_store,
    )

    detector = YouTubeDuplicateDetector(settings=settings)

    assert detector._store is selected_store
    assert seen == [settings]
    assert not (tmp_path / "memory.db").exists()


def test_duplicate_detector_preserves_explicit_store_injection(monkeypatch, tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "memory.db"))
    injected_store = object()

    def fail_if_selected(_settings):
        raise AssertionError("selector must not run when a store is explicitly injected")

    monkeypatch.setattr(
        "app.services.youtube_duplicate_service.get_youtube_memory_store",
        fail_if_selected,
    )

    detector = YouTubeDuplicateDetector(store=injected_store, settings=settings)

    assert detector._store is injected_store
    assert not (tmp_path / "memory.db").exists()

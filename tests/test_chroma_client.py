"""Tests for ChromaDB persistent client setup."""

from pathlib import Path

from app.config import Settings
from app.db.chroma_client import get_collection, reset_chroma_cache


class TestChromaClient:
    def test_creates_persist_directory(self, test_settings: Settings) -> None:
        reset_chroma_cache()
        get_collection(test_settings)
        assert Path(test_settings.chroma_persist_dir).exists()

    def test_collection_is_empty_on_first_use(self, test_settings: Settings) -> None:
        reset_chroma_cache()
        collection = get_collection(test_settings)
        assert collection.count() == 0

    def test_get_or_create_returns_same_collection(self, test_settings: Settings) -> None:
        reset_chroma_cache()
        first = get_collection(test_settings)
        second = get_collection(test_settings)
        assert first.name == second.name == test_settings.chroma_collection_name

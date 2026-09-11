"""Regression coverage for the P-03 Memory Intelligence topic-store cutover."""

from __future__ import annotations

import inspect

from app.services.memory_intelligence_service import MemoryIntelligenceService


_TOPIC_METHODS = (
    "upsert_topic",
    "find_topic_by_name",
    "topics_for_video",
    "list_topics",
    "get_topic",
)


def test_memory_intelligence_initializes_selected_topic_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService.__init__)

    assert "get_topic_store(self._settings)" in source
    # Preserve explicit store injection for legacy/unit-test callers while
    # production follows the selected persistence backend.
    assert "store if store is not None else get_topic_store" in source


def test_topic_reads_and_writes_do_not_use_legacy_intelligence_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService)

    for method in _TOPIC_METHODS:
        assert f"self._store.{method}(" not in source

    assert "self._topics.upsert_topic(" in source
    assert "self._topics.find_topic_by_name(" in source
    assert "self._topics.topics_for_video(" in source
    assert "self._topics.list_topics(" in source
    assert "self._topics.get_topic(" in source

"""Regression coverage for the P-03 Memory Intelligence learning-edge cutover."""

from __future__ import annotations

import inspect

from app.services.memory_intelligence_service import MemoryIntelligenceService


_EDGE_METHODS = (
    "upsert_edge",
    "edges_for_video",
    "edges_for_topic_videos",
    "count_edges",
)


def test_memory_intelligence_initializes_selected_learning_edge_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService.__init__)

    assert "get_learning_edge_store(self._settings)" in source
    # Preserve explicit store injection for legacy/unit-test callers while
    # production follows the selected persistence backend.
    assert "store if store is not None else get_learning_edge_store" in source


def test_learning_edge_reads_and_writes_do_not_use_legacy_intelligence_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService)

    for method in _EDGE_METHODS:
        assert f"self._store.{method}(" not in source

    assert "self._edges.upsert_edge(" in source
    assert "self._edges.edges_for_video(" in source
    assert "self._edges.edges_for_topic_videos(" in source
    assert "self._edges.count_edges(" in source

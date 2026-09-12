"""Regression coverage for the P-03 Memory Intelligence event-store cutover."""

from __future__ import annotations

import inspect

from app.services.memory_intelligence_service import MemoryIntelligenceService


_EVENT_METHODS = ("record_event", "recent_events", "save_dates")


def test_memory_intelligence_initializes_selected_event_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService.__init__)

    assert "get_intelligence_event_store(self._settings)" in source
    assert "store if store is not None else get_intelligence_event_store" in source


def test_event_reads_and_writes_do_not_use_legacy_intelligence_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService)

    for method in _EVENT_METHODS:
        assert f"self._store.{method}(" not in source

    assert "self._events.record_event(" in source
    assert "self._events.recent_events(" in source
    assert "self._events.save_dates(" in source

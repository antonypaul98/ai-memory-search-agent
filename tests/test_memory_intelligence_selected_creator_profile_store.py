"""Regression coverage for the P-03 Memory Intelligence creator-profile cutover."""

from __future__ import annotations

import inspect

from app.services.memory_intelligence_service import MemoryIntelligenceService


_CREATOR_METHODS = (
    "replace_creator_stats",
    "list_creators",
    "get_creator",
    "find_creator_by_name",
)


def test_memory_intelligence_initializes_selected_creator_profile_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService.__init__)

    assert "get_creator_profile_store(self._settings)" in source
    # Preserve explicit store injection for legacy/unit-test callers while
    # production follows the selected persistence backend.
    assert "store if store is not None else get_creator_profile_store" in source


def test_creator_profile_reads_and_writes_do_not_use_legacy_intelligence_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService)

    for method in _CREATOR_METHODS:
        assert f"self._store.{method}(" not in source

    assert "self._creators.replace_creator_stats(" in source
    assert "self._creators.list_creators(" in source
    assert "self._creators.get_creator(" in source
    assert "self._creators.find_creator_by_name(" in source

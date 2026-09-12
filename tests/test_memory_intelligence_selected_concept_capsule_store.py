"""Regression coverage for the P-03 Memory Intelligence concept-capsule cutover."""

from __future__ import annotations

import inspect

from app.services.memory_intelligence_service import MemoryIntelligenceService


_CAPSULE_METHODS = (
    "upsert_concept_capsule",
    "list_concept_capsules",
    "get_concept_capsule",
)


def test_memory_intelligence_initializes_selected_concept_capsule_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService.__init__)

    assert "get_concept_capsule_store(self._settings)" in source
    # Preserve explicit store injection for legacy/unit-test callers while
    # production follows the selected persistence backend.
    assert "store if store is not None else get_concept_capsule_store" in source


def test_concept_capsule_reads_and_writes_do_not_use_legacy_intelligence_store() -> None:
    source = inspect.getsource(MemoryIntelligenceService)

    for method in _CAPSULE_METHODS:
        assert f"self._store.{method}(" not in source

    assert "self._capsules.upsert_concept_capsule(" in source
    assert "self._capsules.list_concept_capsules(" in source
    assert "self._capsules.get_concept_capsule(" in source

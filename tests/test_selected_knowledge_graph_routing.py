"""Regression tests for the selected knowledge-graph persistence boundary."""

from unittest.mock import MagicMock

import app.services.knowledge_graph_service as knowledge_graph_service_module
from app.services.knowledge_graph_service import KnowledgeGraphService


def test_service_uses_selected_knowledge_graph_store(monkeypatch, test_settings) -> None:
    selected = MagicMock(name="selected-knowledge-graph-store")
    factory = MagicMock(return_value=selected)
    monkeypatch.setattr(
        knowledge_graph_service_module,
        "get_selected_knowledge_graph_store",
        factory,
    )

    service = KnowledgeGraphService(settings=test_settings)

    factory.assert_called_once_with(test_settings)
    assert service._store is selected


def test_explicit_store_injection_bypasses_selected_factory(monkeypatch, test_settings) -> None:
    injected = MagicMock(name="injected-knowledge-graph-store")
    factory = MagicMock()
    monkeypatch.setattr(
        knowledge_graph_service_module,
        "get_selected_knowledge_graph_store",
        factory,
    )

    service = KnowledgeGraphService(settings=test_settings, store=injected)

    factory.assert_not_called()
    assert service._store is injected

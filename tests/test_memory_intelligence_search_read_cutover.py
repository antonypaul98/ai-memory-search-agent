"""Regression coverage for the P-03 Memory Intelligence search-read cutover."""

from __future__ import annotations

import inspect

from app.services.memory_intelligence_service import MemoryIntelligenceService


def test_insights_uses_only_canonical_search_event_stream() -> None:
    """Insights must not reopen the legacy agent-search SQLite table.

    Agent/extension searches are mirrored into the canonical tenant-scoped
    intelligence event stream, so reading agent_search_events here would both
    bypass the selected persistence boundary and double-count mirrored queries.
    """

    source = inspect.getsource(MemoryIntelligenceService.insights)

    assert 'recent_events(user_id, event_type="search"' in source
    assert "agent_search_events" not in source
    assert "get_connection" not in source
    assert "migrate(" not in source

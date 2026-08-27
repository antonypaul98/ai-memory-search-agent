"""Phase 2 search-filter API and workspace regression tests."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.models.intelligence import NaturalRetrieveResponse


def test_natural_retrieve_passes_trimmed_save_reason(client: TestClient) -> None:
    with patch(
        "app.services.memory_intelligence_service.MemoryIntelligenceService.retrieve",
        return_value=NaturalRetrieveResponse(query="rag", results=[]),
    ) as retrieve:
        response = client.get(
            "/api/v1/intelligence/retrieve",
            params={"q": "rag", "save_reason": "  interview prep  "},
        )

    assert response.status_code == 200
    filters = retrieve.call_args.kwargs["filters"]
    assert filters.save_reason == "interview prep"


def test_natural_retrieve_treats_blank_save_reason_as_unset(client: TestClient) -> None:
    with patch(
        "app.services.memory_intelligence_service.MemoryIntelligenceService.retrieve",
        return_value=NaturalRetrieveResponse(query="rag", results=[]),
    ) as retrieve:
        response = client.get(
            "/api/v1/intelligence/retrieve",
            params={"q": "rag", "save_reason": "   "},
        )

    assert response.status_code == 200
    filters = retrieve.call_args.kwargs["filters"]
    assert filters.save_reason is None


def test_workspace_exposes_and_forwards_save_reason_filter() -> None:
    source = Path("app/static/js/views/search.js").read_text(encoding="utf-8")
    assert 'id="f-save-reason"' in source
    assert 'save_reason: $("#f-save-reason", root).value.trim() || undefined' in source

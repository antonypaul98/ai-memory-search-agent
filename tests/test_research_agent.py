"""Phase 4c read-only Research Agent tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.research_agent import ResearchAgentRequest
from app.services.research_agent import ResearchAgent


def _search_response(rows: list[dict]) -> MagicMock:
    response = MagicMock()
    response.model_dump.return_value = {"results": rows}
    return response


class TestResearchAgent:
    def test_multi_hop_research_is_tenant_scoped_and_cited(
        self, test_settings: Settings
    ) -> None:
        first = [
            {
                "video_id": "v1",
                "source_type": "youtube",
                "title": "RAG foundations",
                "matched_text": "Retrieval grounds model answers.",
                "citation_ref": "https://youtu.be/v1?t=10",
                "relevance_score": 0.92,
            },
            {
                "video_id": "v2",
                "source_type": "youtube",
                "title": "Vector search",
                "matched_text": "Embeddings retrieve semantically similar chunks.",
                "citation_ref": "https://youtu.be/v2?t=20",
                "relevance_score": 0.88,
            },
        ]
        second = [
            first[0],
            {
                "video_id": "v3",
                "source_type": "youtube",
                "title": "Grounded generation",
                "matched_text": "Citations make answers verifiable.",
                "citation_ref": "https://youtu.be/v3?t=30",
                "relevance_score": 0.84,
            },
        ]
        with patch("app.services.research_agent.SearchService") as MockSearch:
            MockSearch.return_value.search.side_effect = [
                _search_response(first),
                _search_response(second),
            ]
            out = ResearchAgent(test_settings).run(
                user_id="tenant-a",
                request=ResearchAgentRequest(
                    question="How does RAG stay grounded?",
                    depth=2,
                    max_sources=6,
                ),
            )

        assert len(out.sources) == 3
        assert [s.source_id for s in out.sources] == [
            "youtube:v1",
            "youtube:v2",
            "youtube:v3",
        ]
        assert "[S1]" in out.report and "[S3]" in out.report
        assert "https://youtu.be/v3?t=30" in out.report
        assert out.grounded is True
        assert MockSearch.return_value.search.call_count == 2
        for call in MockSearch.return_value.search.call_args_list:
            assert call.kwargs["user_id"] == "tenant-a"

    def test_depth_and_source_count_are_bounded_by_model(self) -> None:
        try:
            ResearchAgentRequest(question="x", depth=4, max_sources=6)
            assert False, "depth above 3 must be rejected"
        except Exception:
            pass
        try:
            ResearchAgentRequest(question="x", depth=2, max_sources=2)
            assert False, "research requires room for at least three sources"
        except Exception:
            pass

    def test_empty_memory_does_not_fabricate_sources(self, test_settings: Settings) -> None:
        with patch("app.services.research_agent.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = _search_response([])
            out = ResearchAgent(test_settings).run(
                user_id="tenant-a",
                request=ResearchAgentRequest(question="unknown topic", depth=2),
            )
        assert out.sources == []
        assert "could not find evidence" in out.report.lower()
        assert "No external sources were used." in out.report


class TestResearchAgentAPI:
    def test_research_endpoint_uses_authenticated_demo_user(self, client: TestClient) -> None:
        rows = [
            {
                "video_id": "v1",
                "source_type": "youtube",
                "title": "Demo",
                "matched_text": "Saved evidence",
                "citation_ref": "https://youtu.be/v1?t=1",
                "relevance_score": 0.9,
            }
        ]
        with patch("app.services.research_agent.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = _search_response(rows)
            resp = client.post(
                "/api/v1/agents/research",
                json={"question": "What did I save?", "depth": 1, "max_sources": 3},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["grounded"] is True
        assert body["sources"][0]["source_id"] == "youtube:v1"
        assert MockSearch.return_value.search.call_args.kwargs["user_id"] == "local-default"

    def test_research_endpoint_rejects_invalid_depth(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agents/research",
            json={"question": "x", "depth": 9, "max_sources": 3},
        )
        assert resp.status_code == 422

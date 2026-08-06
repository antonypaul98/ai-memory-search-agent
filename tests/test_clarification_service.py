"""Tests for clarifying question detection."""

from app.services.clarification_service import analyze_clarification, filter_chunks_by_choice


class TestClarificationService:
    def test_wiring_question_offers_domain_options(self) -> None:
        chunks = [
            {
                "video_id": "pc1",
                "title": "PC build wiring",
                "matched_text": "Connect the 24-pin PSU cable to the motherboard header.",
                "relevance_score": 0.7,
            },
            {
                "video_id": "house1",
                "title": "House wiring safety",
                "matched_text": "Turn off the breaker before touching outlet wiring.",
                "relevance_score": 0.69,
            },
        ]
        result = analyze_clarification("What wiring precautions should I take?", chunks)
        assert result.needs_clarification is True
        assert any(opt.label == "PC wiring" for opt in result.options or [])

    def test_filter_chunks_by_pc_wiring_choice(self) -> None:
        chunks = [
            {
                "matched_text": "Connect the 24-pin PSU cable to the motherboard header.",
                "title": "PC build wiring",
                "relevance_score": 0.7,
            },
            {
                "matched_text": "Turn off the breaker before touching outlet wiring.",
                "title": "House wiring safety",
                "relevance_score": 0.69,
            },
        ]
        filtered = filter_chunks_by_choice(chunks, "PC wiring")
        assert len(filtered) == 1
        assert "24-pin" in filtered[0]["matched_text"]

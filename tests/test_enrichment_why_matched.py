"""Tests for enriched search responses."""

from app.services.enrichment_service import build_why_matched


class TestBuildWhyMatched:
    def test_includes_transcript_title_and_score(self) -> None:
        text = build_why_matched(
            query="protein meals",
            matched_text="high protein chicken bowl for lunch",
            title="Protein Meal Prep Guide",
            description="Learn protein-focused meal prep strategies.",
            relevance_score=0.87,
            start_time=12.0,
        )
        assert "Transcript passage matched" in text
        assert "Title also contains" in text
        assert "Relevance score: 0.87" in text

    def test_description_match_when_terms_overlap(self) -> None:
        text = build_why_matched(
            query="meal prep",
            matched_text="prep containers on Sunday",
            title="Kitchen Setup",
            description="Weekly meal prep workflow for beginners.",
            relevance_score=0.75,
        )
        assert "Description also mentions" in text

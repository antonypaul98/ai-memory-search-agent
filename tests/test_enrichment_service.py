"""Tests for deterministic video enrichment."""

from app.services.enrichment_service import enrich_video


class TestEnrichVideo:
    def test_output_shape(self) -> None:
        result = enrich_video(
            title="Healthy Meal Prep",
            description="A guide to high-protein lunches for busy weeks.",
            channel="Chef Alex",
            transcript_text=(
                "Today we make a high protein chicken bowl. "
                "Try prepping ingredients on Sunday for the week."
            ),
            chunk_texts=["Today we make a high protein chicken bowl."],
        )
        assert result.one_line_memory.startswith("Healthy Meal Prep —")
        assert 1 <= len(result.why_saved) <= 3
        assert isinstance(result.action_items, list)

    def test_no_fabricated_action_items_for_plain_transcript(self) -> None:
        result = enrich_video(
            title="Ambient Music Mix",
            description="Relaxing background music for studying.",
            channel="LoFi Channel",
            transcript_text=(
                "This track was recorded in the studio last year. "
                "The melody repeats softly throughout the piece."
            ),
            chunk_texts=["This track was recorded in the studio last year."],
        )
        assert result.action_items == []

    def test_extracts_grounded_action_items(self) -> None:
        result = enrich_video(
            title="Morning Routine",
            description="",
            channel="Coach",
            transcript_text=(
                "Try starting your day with a five minute stretch routine. "
                "Make sure you drink water before coffee."
            ),
            chunk_texts=["Try starting your day with a five minute stretch routine."],
        )
        assert result.action_items
        assert all("Try" in item or "Make sure" in item for item in result.action_items)

    def test_why_saved_uses_channel_and_keywords(self) -> None:
        result = enrich_video(
            title="Protein Meal Prep Guide",
            description="Learn protein-focused meal prep strategies.",
            channel="Nutrition Lab",
            transcript_text="protein protein protein chicken meal prep bowls",
            chunk_texts=["protein chicken meal prep bowls"],
        )
        assert any("Nutrition Lab" in reason for reason in result.why_saved)

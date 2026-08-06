"""Tests for deterministic answer generation."""

from app.services.answer_generator import (
    INSUFFICIENT_EVIDENCE_MESSAGE,
    DeterministicAnswerGenerator,
    dedupe_sentences,
)


class TestDeterministicAnswerGenerator:
    def test_procedural_question_uses_bullets(self) -> None:
        generator = DeterministicAnswerGenerator()
        chunks = [
            {
                "matched_text": (
                    "First download the GPU driver from the vendor site. "
                    "Next install the CUDA toolkit on your machine."
                ),
                "relevance_score": 0.82,
            }
        ]
        result = generator.generate("How do I install the GPU?", chunks)
        assert result.grounded is True
        assert "1." in result.answer

    def test_insufficient_evidence_when_no_chunks(self) -> None:
        generator = DeterministicAnswerGenerator()
        result = generator.generate("How do I install the GPU?", [])
        assert result.grounded is False
        assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE

    def test_insufficient_evidence_when_scores_are_weak(self) -> None:
        generator = DeterministicAnswerGenerator()
        chunks = [{"matched_text": "unrelated ambient music", "relevance_score": 0.05}]
        result = generator.generate("How do I install the GPU?", chunks)
        assert result.grounded is False
        assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE

    def test_conceptual_question_uses_paragraph(self) -> None:
        generator = DeterministicAnswerGenerator()
        chunks = [
            {
                "matched_text": (
                    "Protein supports muscle recovery after training sessions. "
                    "Balanced meals help maintain steady energy levels."
                ),
                "relevance_score": 0.76,
            }
        ]
        result = generator.generate("Summarize protein benefits", chunks)
        assert result.grounded is True
        assert "protein" in result.answer.lower()


class TestDedupeSentences:
    def test_removes_duplicate_sentences(self) -> None:
        sentences = [
            "Install the GPU driver first.",
            "Install the GPU driver first.",
            "Connect the power cable next.",
        ]
        deduped = dedupe_sentences(sentences)
        assert len(deduped) == 2

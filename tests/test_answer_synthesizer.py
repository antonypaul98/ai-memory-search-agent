"""Tests for grounded answer synthesis."""

from app.services.answer_synthesizer import synthesize_answer


class TestAnswerSynthesizer:
    def test_pc_components_question_returns_bullet_list(self) -> None:
        chunks = [
            {
                "matched_text": (
                    "For this build you'll need a CPU, motherboard, RAM, SSD, power supply, "
                    "case, cooler, and maybe a graphics card."
                ),
                "relevance_score": 0.82,
            }
        ]
        result = synthesize_answer("What components are required for a PC build?", chunks)
        assert result.grounded is True
        assert "• CPU" in result.answer
        assert "Motherboard" in result.answer

    def test_procedural_question_returns_numbered_steps(self) -> None:
        chunks = [
            {
                "matched_text": (
                    "First download the GPU driver from the vendor site. "
                    "Next install the CUDA toolkit on your machine."
                ),
                "relevance_score": 0.82,
            }
        ]
        result = synthesize_answer("How do I install the GPU?", chunks)
        assert result.grounded is True
        assert "1." in result.answer

    def test_insufficient_evidence_when_scores_are_weak(self) -> None:
        chunks = [{"matched_text": "unrelated ambient music", "relevance_score": 0.05}]
        result = synthesize_answer("What GPU did I save?", chunks)
        assert result.grounded is False

    def test_summary_question_returns_bullets(self) -> None:
        chunks = [
            {
                "matched_text": (
                    "Protein supports muscle recovery after training sessions. "
                    "Balanced meals help maintain steady energy levels."
                ),
                "relevance_score": 0.76,
            }
        ]
        result = synthesize_answer("Summarize this", chunks)
        assert result.grounded is True
        assert "•" in result.answer

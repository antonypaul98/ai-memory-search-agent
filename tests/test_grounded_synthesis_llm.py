"""Grounding contract tests for optional LLM synthesis."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.models.capsule import StructuredAnswer
from app.services.grounded_synthesis import synthesize_grounded_answer


def _settings() -> Settings:
    return Settings(
        llm_provider="ollama",
        llm_model="test-model",
        sqlite_path=":memory:",
        chroma_persist_dir="./data/test-chroma-grounding",
    )


def _chunks() -> list[dict]:
    return [
        {
            "video_id": "vid1",
            "start_time": 12.0,
            "matched_text": "Docker Compose starts the application services together.",
            "relevance_score": 0.95,
        }
    ]


class TestGroundedLLMContract:
    def test_valid_cited_llm_answer_is_used(self) -> None:
        provider = MagicMock()
        provider.synthesize.return_value = StructuredAnswer(
            answer_markdown="Docker Compose starts the application services together.",
            evidence_ids=["vid1@12"],
            confidence="high",
        )
        with patch("app.services.grounded_synthesis.get_llm_provider", return_value=provider):
            generated, confidence, _elapsed = synthesize_grounded_answer(
                "How are the services started?",
                _chunks(),
                settings=_settings(),
            )
        assert generated.answer.startswith("Docker Compose")
        assert generated.grounded is True
        assert confidence == "high"

    def test_fabricated_evidence_id_falls_back_to_deterministic_answer(self) -> None:
        provider = MagicMock()
        provider.synthesize.return_value = StructuredAnswer(
            answer_markdown="Hallucinated external fact that is not in memory.",
            evidence_ids=["made-up@999"],
            confidence="high",
        )
        with patch("app.services.grounded_synthesis.get_llm_provider", return_value=provider):
            generated, confidence, _elapsed = synthesize_grounded_answer(
                "Summarize how the services start",
                _chunks(),
                settings=_settings(),
            )
        assert generated.answer != "Hallucinated external fact that is not in memory."
        assert "Docker Compose" in generated.answer
        assert generated.grounded is True
        assert confidence == "high"

    def test_missing_evidence_ids_falls_back(self) -> None:
        provider = MagicMock()
        provider.synthesize.return_value = StructuredAnswer(
            answer_markdown="Unsupported answer",
            evidence_ids=[],
            confidence="high",
        )
        with patch("app.services.grounded_synthesis.get_llm_provider", return_value=provider):
            generated, _confidence, _elapsed = synthesize_grounded_answer(
                "Summarize how the services start",
                _chunks(),
                settings=_settings(),
            )
        assert generated.answer != "Unsupported answer"
        assert generated.grounded is True

    def test_low_confidence_llm_answer_falls_back(self) -> None:
        provider = MagicMock()
        provider.synthesize.return_value = StructuredAnswer(
            answer_markdown="Docker Compose might start services.",
            evidence_ids=["vid1@12"],
            confidence="low",
        )
        with patch("app.services.grounded_synthesis.get_llm_provider", return_value=provider):
            generated, confidence, _elapsed = synthesize_grounded_answer(
                "Summarize how the services start",
                _chunks(),
                settings=_settings(),
            )
        assert generated.answer != "Docker Compose might start services."
        assert generated.grounded is True
        assert confidence == "high"

    def test_provider_exception_never_breaks_deterministic_path(self) -> None:
        provider = MagicMock()
        provider.synthesize.side_effect = RuntimeError("provider unavailable")
        with patch("app.services.grounded_synthesis.get_llm_provider", return_value=provider):
            generated, _confidence, _elapsed = synthesize_grounded_answer(
                "Summarize how the services start",
                _chunks(),
                settings=_settings(),
            )
        assert "Docker Compose" in generated.answer
        assert generated.grounded is True

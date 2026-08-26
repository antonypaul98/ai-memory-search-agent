"""Contract tests for optional LLM providers.

External services are mocked so CI never requires credentials or network access.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.services.llm_provider import (
    OllamaProvider,
    OpenAICompatibleProvider,
    get_llm_provider,
)


def _settings(**overrides) -> Settings:
    values = {
        "llm_provider": "none",
        "llm_base_url": "http://llm.local:11434",
        "llm_model": "test-model",
        "llm_api_key_env": "TEST_LLM_API_KEY",
        "llm_timeout_sec": 7,
        "sqlite_path": ":memory:",
        "chroma_persist_dir": "./data/test-chroma",
    }
    values.update(overrides)
    return Settings(**values)


def _mock_client(response_json: dict):
    response = MagicMock()
    response.json.return_value = response_json
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.post.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False
    return context, client


class TestProviderSelection:
    def test_none_disables_optional_llm(self) -> None:
        assert get_llm_provider(_settings(llm_provider="none")) is None

    def test_ollama_selection(self) -> None:
        assert isinstance(get_llm_provider(_settings(llm_provider="ollama")), OllamaProvider)

    def test_openai_compatible_selection(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_LLM_API_KEY", "secret")
        assert isinstance(
            get_llm_provider(_settings(llm_provider="openai_compatible")),
            OpenAICompatibleProvider,
        )


class TestOllamaContract:
    def test_uses_ollama_chat_endpoint(self) -> None:
        context, client = _mock_client({"message": {"content": "{\"ok\": true}"}})
        with patch("app.services.llm_provider.httpx.Client", return_value=context):
            provider = OllamaProvider(_settings(llm_provider="ollama"))
            raw = provider.generate_capsule_json(
                title="Demo",
                description="Description",
                transcript_excerpt="Transcript",
                reflection_goal="Learn",
            )
        assert raw == '{"ok": true}'
        args, kwargs = client.post.call_args
        assert args[0] == "http://llm.local:11434/api/chat"
        assert kwargs["json"]["model"] == "test-model"
        assert "headers" not in kwargs


class TestOpenAICompatibleContract:
    def test_missing_api_key_falls_back_without_http(self, monkeypatch) -> None:
        monkeypatch.delenv("TEST_LLM_API_KEY", raising=False)
        provider = OpenAICompatibleProvider(_settings(llm_provider="openai_compatible"))
        with patch("app.services.llm_provider.httpx.Client") as mock_client:
            result = provider.generate_capsule_json(
                title="Demo",
                description="Description",
                transcript_excerpt="Transcript",
                reflection_goal="Learn",
            )
        assert result is None
        mock_client.assert_not_called()

    def test_missing_model_falls_back_without_http(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_LLM_API_KEY", "secret")
        provider = OpenAICompatibleProvider(
            _settings(llm_provider="openai_compatible", llm_model="")
        )
        with patch("app.services.llm_provider.httpx.Client") as mock_client:
            result = provider.synthesize(question="Q", evidence=[], answer_format="concise")
        assert result is None
        mock_client.assert_not_called()

    def test_calls_v1_chat_completions_with_bearer_key(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_LLM_API_KEY", "top-secret")
        answer = {
            "answer_markdown": "Grounded answer",
            "answer_type": "general",
            "evidence_ids": ["vid@12"],
            "confidence": "high",
            "missing_information": [],
        }
        context, client = _mock_client(
            {"choices": [{"message": {"content": json.dumps(answer)}}]}
        )
        with patch("app.services.llm_provider.httpx.Client", return_value=context):
            provider = OpenAICompatibleProvider(
                _settings(llm_provider="openai_compatible", llm_base_url="https://api.example.test")
            )
            result = provider.synthesize(
                question="What did I save?",
                evidence=[{"evidence_id": "vid@12", "matched_text": "Grounded evidence"}],
                answer_format="concise",
            )
        assert result is not None
        assert result.answer_markdown == "Grounded answer"
        args, kwargs = client.post.call_args
        assert args[0] == "https://api.example.test/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer top-secret"
        assert kwargs["json"]["model"] == "test-model"
        prompt = kwargs["json"]["messages"][0]["content"]
        assert "[vid@12]" in prompt
        assert "Answer ONLY from the supplied evidence" in prompt

    def test_base_url_already_ending_v1_is_not_duplicated(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_LLM_API_KEY", "secret")
        context, client = _mock_client({"choices": [{"message": {"content": "{}"}}]})
        with patch("app.services.llm_provider.httpx.Client", return_value=context):
            provider = OpenAICompatibleProvider(
                _settings(
                    llm_provider="openai_compatible",
                    llm_base_url="https://api.example.test/v1",
                )
            )
            provider.generate_capsule_json(
                title="Demo",
                description="Description",
                transcript_excerpt="Transcript",
                reflection_goal="Learn",
            )
        args, _kwargs = client.post.call_args
        assert args[0] == "https://api.example.test/v1/chat/completions"

    def test_malformed_structured_answer_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_LLM_API_KEY", "secret")
        context, _client = _mock_client(
            {"choices": [{"message": {"content": "not-json"}}]}
        )
        with patch("app.services.llm_provider.httpx.Client", return_value=context):
            provider = OpenAICompatibleProvider(_settings(llm_provider="openai_compatible"))
            assert provider.synthesize(
                question="Q",
                evidence=[{"evidence_id": "e1", "matched_text": "Evidence"}],
                answer_format="concise",
            ) is None

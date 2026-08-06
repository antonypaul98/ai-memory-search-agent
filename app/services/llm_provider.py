"""Optional LLM providers for capsule generation and synthesis."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.models.capsule import StructuredAnswer


class LLMProvider(ABC):
    @abstractmethod
    def generate_capsule_json(
        self, *, title: str, description: str, transcript_excerpt: str, reflection_goal: str
    ) -> str | None:
        ...

    @abstractmethod
    def synthesize(
        self, *, question: str, evidence: list[dict], answer_format: str
    ) -> StructuredAnswer | None:
        ...


class OllamaProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.llm_model or "llama3.2"

    def generate_capsule_json(self, **kwargs: Any) -> str | None:
        prompt = (
            "Return ONLY valid JSON for a memory capsule with fields: video_id, title, "
            "one_line_memory, short_summary, topics, entities, tools_or_components, "
            "procedures, claims, difficulty, content_style, creator, duration, "
            "upload_date, save_reason, user_goal, sections."
            f"\nTitle: {kwargs.get('title')}\nDescription: {kwargs.get('description')}"
            f"\nGoal: {kwargs.get('reflection_goal')}\nTranscript:\n{kwargs.get('transcript_excerpt')[:4000]}"
        )
        return _post_chat(self._settings.llm_base_url, self._model, prompt, self._settings.llm_timeout_sec)

    def synthesize(self, *, question: str, evidence: list[dict], answer_format: str) -> StructuredAnswer | None:
        evidence_text = "\n".join(
            f"[{i}] {e.get('matched_text', '')[:400]}" for i, e in enumerate(evidence[:8])
        )
        prompt = (
            "Answer ONLY from evidence. Return JSON with answer_markdown, answer_type, "
            "evidence_ids, confidence, missing_information.\n"
            f"Format: {answer_format}\nQuestion: {question}\nEvidence:\n{evidence_text}"
        )
        raw = _post_chat(self._settings.llm_base_url, self._model, prompt, self._settings.llm_timeout_sec)
        if not raw:
            return None
        try:
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                return None
            data = json.loads(match.group(0))
            return StructuredAnswer.model_validate(data)
        except Exception:
            return None


class OpenAICompatibleProvider(OllamaProvider):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._api_key = os.environ.get(settings.llm_api_key_env, "")

    def generate_capsule_json(self, **kwargs: Any) -> str | None:
        if not self._api_key:
            return None
        return super().generate_capsule_json(**kwargs)


def _post_chat(base_url: str, model: str, prompt: str, timeout: int) -> str | None:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content") or data.get("response")
    except Exception:
        return None


def get_llm_provider(settings: Settings | None = None) -> LLMProvider | None:
    settings = settings or get_settings()
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings)
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    return None

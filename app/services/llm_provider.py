"""Optional LLM providers for capsule generation and grounded synthesis."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.models.capsule import StructuredAnswer
from app.models.user import LOCAL_DEFAULT_USER_ID


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
        return _post_ollama_chat(
            self._settings.llm_base_url,
            self._model,
            _capsule_prompt(kwargs),
            self._settings.llm_timeout_sec,
        )

    def synthesize(
        self, *, question: str, evidence: list[dict], answer_format: str
    ) -> StructuredAnswer | None:
        raw = _post_ollama_chat(
            self._settings.llm_base_url,
            self._model,
            _synthesis_prompt(question, evidence, answer_format),
            self._settings.llm_timeout_sec,
        )
        return _parse_structured_answer(raw)


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible `/v1/chat/completions` servers.

    The API key is loaded only from the configured environment variable and is
    never persisted in repository state or logs. Missing model/key fails closed
    to the deterministic non-LLM path.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.llm_model.strip()
        self._api_key = os.environ.get(settings.llm_api_key_env, "").strip()

    @property
    def configured(self) -> bool:
        return bool(self._model and self._api_key)

    def generate_capsule_json(self, **kwargs: Any) -> str | None:
        if not self.configured:
            return None
        return _post_openai_chat(
            self._settings.llm_base_url,
            self._model,
            _capsule_prompt(kwargs),
            self._settings.llm_timeout_sec,
            self._api_key,
        )

    def synthesize(
        self, *, question: str, evidence: list[dict], answer_format: str
    ) -> StructuredAnswer | None:
        if not self.configured:
            return None
        raw = _post_openai_chat(
            self._settings.llm_base_url,
            self._model,
            _synthesis_prompt(question, evidence, answer_format),
            self._settings.llm_timeout_sec,
            self._api_key,
        )
        return _parse_structured_answer(raw)


class RoutedLLMProvider(LLMProvider):
    """Use the Model Router for optional capsule/synthesis inference.

    The caller may set MODEL_ROUTER_PINNED_MODEL to force one exact model. Without
    a pin, task-aware automatic routing is used. Failures return None so the existing
    deterministic grounding path remains authoritative.
    """

    def __init__(self, settings: Settings, *, user_id: str | None = None) -> None:
        from app.services.model_router import ModelRouter

        self._settings = settings
        self._user_id = user_id or LOCAL_DEFAULT_USER_ID
        self._router = ModelRouter(settings)

    def _route(self, prompt: str, *, task_type: str, max_output_tokens: int) -> str | None:
        from app.models.model_router import (
            ModelRouteMode,
            ModelRouteRequest,
            ModelTaskType,
        )
        from app.services.model_router import ModelRouteError

        pin = self._settings.model_router_pinned_model.strip()
        mode = ModelRouteMode.PINNED if pin else ModelRouteMode.AUTO
        try:
            result = self._router.route(
                ModelRouteRequest(
                    prompt=prompt,
                    mode=mode,
                    pinned_model=pin or None,
                    task_type=ModelTaskType(task_type),
                    prefer_free=True,
                    max_output_tokens=max_output_tokens,
                    max_latency_ms=max(100, self._settings.llm_timeout_sec * 1000),
                ),
                user_id=self._user_id,
            )
            return result.content
        except (ModelRouteError, ValueError):
            return None

    def generate_capsule_json(self, **kwargs: Any) -> str | None:
        return self._route(
            _capsule_prompt(kwargs),
            task_type="extraction",
            max_output_tokens=1400,
        )

    def synthesize(
        self, *, question: str, evidence: list[dict], answer_format: str
    ) -> StructuredAnswer | None:
        raw = self._route(
            _synthesis_prompt(question, evidence, answer_format),
            task_type="reasoning",
            max_output_tokens=1200,
        )
        return _parse_structured_answer(raw)


def _capsule_prompt(kwargs: dict[str, Any]) -> str:
    transcript = str(kwargs.get("transcript_excerpt") or "")[:4000]
    return (
        "Return ONLY valid JSON for a memory capsule with fields: video_id, title, "
        "one_line_memory, short_summary, topics, entities, tools_or_components, "
        "procedures, claims, difficulty, content_style, creator, duration, "
        "upload_date, save_reason, user_goal, sections."
        f"\nTitle: {kwargs.get('title')}\nDescription: {kwargs.get('description')}"
        f"\nGoal: {kwargs.get('reflection_goal')}\nTranscript:\n{transcript}"
    )


def _synthesis_prompt(question: str, evidence: list[dict], answer_format: str) -> str:
    lines: list[str] = []
    for i, item in enumerate(evidence[:8]):
        evidence_id = item.get("evidence_id") or item.get("doc_id") or str(i)
        text = str(item.get("matched_text") or "")[:400]
        lines.append(f"[{evidence_id}] {text}")
    evidence_text = "\n".join(lines)
    return (
        "Answer ONLY from the supplied evidence. Return JSON with answer_markdown, "
        "answer_type, evidence_ids, confidence, missing_information. evidence_ids must "
        "contain only IDs shown in brackets below.\n"
        f"Format: {answer_format}\nQuestion: {question}\nEvidence:\n{evidence_text}"
    )


def _parse_structured_answer(raw: str | None) -> StructuredAnswer | None:
    if not raw:
        return None
    try:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        data = json.loads(match.group(0))
        return StructuredAnswer.model_validate(data)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _post_ollama_chat(base_url: str, model: str, prompt: str, timeout: int) -> str | None:
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
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None


def _post_openai_chat(
    base_url: str,
    model: str,
    prompt: str,
    timeout: int,
    api_key: str,
) -> str | None:
    base = base_url.rstrip("/")
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            return choices[0].get("message", {}).get("content")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, IndexError):
        return None


def get_llm_provider(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
) -> LLMProvider | None:
    settings = settings or get_settings()
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings)
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    if settings.llm_provider == "router" and settings.model_router_enabled:
        return RoutedLLMProvider(settings, user_id=user_id)
    return None

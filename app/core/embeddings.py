"""
Sentence Transformers embedding wrapper (lazy singleton).

The model is loaded on first use, not at import time.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from app.config import Settings, get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class EmbeddingModel:
    """Lazy-loaded sentence-transformers model shared across the process."""

    _instance: EmbeddingModel | None = None
    _load_lock = threading.Lock()

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None

    @classmethod
    def get_instance(cls, settings: Settings | None = None) -> EmbeddingModel:
        settings = settings or get_settings()
        with cls._load_lock:
            if cls._instance is None or cls._instance._model_name != settings.embedding_model:
                cls._instance = cls(settings.embedding_model)
            return cls._instance

    def _ensure_loaded(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._load_lock:
            model = self._ensure_loaded()
            vectors = model.encode(texts, convert_to_numpy=True)
        return vectors.tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


def embed_texts(
    texts: list[str], settings: Settings | None = None
) -> list[list[float]]:
    """Embed a batch of document texts."""
    return EmbeddingModel.get_instance(settings).embed_texts(texts)


def embed_query(query: str, settings: Settings | None = None) -> list[float]:
    """Embed a single search query."""
    return EmbeddingModel.get_instance(settings).embed_query(query)


def reset_embedding_model() -> None:
    """Clear cached model — used in tests."""
    EmbeddingModel._instance = None

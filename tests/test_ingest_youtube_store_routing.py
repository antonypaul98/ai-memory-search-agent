"""Regression guards for the P-03 YouTube ingest persistence boundary."""

from __future__ import annotations

import ast
import inspect
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.services import ingest_service
from app.services.ingest_service import IngestService


def test_ingest_service_constructs_selected_youtube_store(tmp_path) -> None:
    settings = Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        sqlite_path=str(tmp_path / "memory.db"),
        jobs_enabled=False,
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
    )
    selected_store = MagicMock()

    with (
        patch(
            "app.services.ingest_service.get_youtube_memory_store",
            return_value=selected_store,
        ) as selector,
        patch("app.services.ingest_service.YouTubeDuplicateDetector") as duplicate_detector,
    ):
        service = IngestService(
            settings=settings,
            metadata_service=MagicMock(),
            transcript_service=MagicMock(),
            repository=MagicMock(),
            registry=MagicMock(),
        )

    assert service._yt_store is selected_store
    selector.assert_called_once_with(settings)
    duplicate_detector.assert_called_once_with(selected_store)


def test_every_ingest_metric_mutation_is_tenant_explicit() -> None:
    tree = ast.parse(inspect.getsource(ingest_service))
    metric_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "bump_metric"
    ]

    assert metric_calls, "Expected IngestService to record YouTube operational metrics"
    for call in metric_calls:
        assert any(keyword.arg == "user_id" for keyword in call.keywords), (
            "Every IngestService YouTube metric mutation must carry tenant identity"
        )

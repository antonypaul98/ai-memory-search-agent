"""Regression guards for P-03 MemoryIntelligenceService storage routing."""

from __future__ import annotations

import ast
from pathlib import Path


SERVICE_PATH = Path("app/services/memory_intelligence_service.py")


def _constructor_tree() -> ast.AST:
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MemoryIntelligenceService"
    )
    return next(
        node
        for node in service.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__init__"
    )


def _called_names(tree: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_constructor_does_not_instantiate_legacy_sqlite_stores() -> None:
    calls = _called_names(_constructor_tree())
    assert "IntelligenceStore" not in calls
    assert "YouTubeMemoryStore" not in calls


def test_constructor_uses_selected_youtube_store_factory() -> None:
    calls = _called_names(_constructor_tree())
    assert "get_youtube_memory_store" in calls

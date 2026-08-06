#!/usr/bin/env python3
"""Trace import times for app.main and dependencies with timestamps."""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

# Allow `python scripts/trace_imports.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TARGETS = [
    "pydantic",
    "pydantic_settings",
    "fastapi",
    "starlette",
    "chromadb",
    "sentence_transformers",
    "yt_dlp",
    "youtube_transcript_api",
    "app.config",
    "app.db.chroma_client",
    "app.db.repositories.memory_repository",
    "app.services.metadata_service",
    "app.services.transcript_service",
    "app.services.ingest_service",
    "app.services.search_service",
    "app.services.chat_service",
    "app.services.answer_generator",
    "app.api.dependencies",
    "app.api.routes.health",
    "app.api.routes.videos",
    "app.api.routes.search",
    "app.api.routes.chat",
    "app.main",
]


def timed_import(name: str) -> float:
    t0 = time.perf_counter()
    sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] importing {name} ... ")
    sys.stdout.flush()
    importlib.import_module(name)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"{elapsed_ms:.0f}ms")
    return elapsed_ms


def main() -> None:
    print("Python:", sys.version.replace("\n", " "))
    print("Executable:", sys.executable)
    print("---")
    total = 0.0
    for name in TARGETS:
        try:
            total += timed_import(name)
        except Exception as exc:
            print(f"FAILED: {exc}")
            raise
    print("---")
    print(f"TOTAL traced imports: {total:.0f}ms")
    print("DONE")


if __name__ == "__main__":
    main()

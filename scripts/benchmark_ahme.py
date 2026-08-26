#!/usr/bin/env python3
"""
Reproducible benchmark comparing flat vs hierarchical AHME pipelines.

Run:
  source .venv_clean/bin/activate
  python scripts/benchmark_ahme.py

CI smoke mode:
  BENCHMARK_RUNS=1 python scripts/benchmark_ahme.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings
from app.db.chroma_client import reset_chroma_cache
from app.db.hierarchical_store import HierarchicalStore
from app.db.repositories.memory_repository import MemoryRepository
from app.models.capsule import MemoryCapsule, MemorySection
from app.services.ahme_engine import AdaptiveHierarchicalMemoryEngine
from app.services.chat_service import ChatService
from app.services.ingest_service import clear_transcript_cache
from app.services.search_service import SearchService
from app.utils.chunking import TranscriptChunk

BENCH_DIR = ROOT / "data" / "benchmark"
REPORT_PATH = ROOT / "docs" / "BENCHMARK_AHME.md"
RUNS = max(1, int(os.environ.get("BENCHMARK_RUNS", "3")))
EMBED_DIM = 384


def _unit_vector(index: int) -> list[float]:
    vec = [0.0] * EMBED_DIM
    vec[index % EMBED_DIM] = 1.0
    return vec


def _mock_embed_query(query: str, settings=None) -> list[float]:
    lowered = query.lower()
    if "protein" in lowered or "meal" in lowered:
        return _unit_vector(0)
    if "cardio" in lowered or "running" in lowered:
        return _unit_vector(1)
    if "gpu" in lowered:
        return _unit_vector(3)
    if "pc" in lowered or "component" in lowered or "compare" in lowered:
        return _unit_vector(2)
    return _unit_vector(0)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[idx]


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"median_ms": 0.0, "p95_ms": 0.0}
    return {
        "median_ms": round(statistics.median(values), 2),
        "p95_ms": round(_percentile(values, 95), 2),
    }


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _seed_data(settings: Settings) -> None:
    reset_chroma_cache()
    repo = MemoryRepository(settings)
    videos = [
        ("video_a", "Protein Meals", "high protein chicken bowl meal prep sunday", 0),
        ("video_b", "Cardio Workout", "running intervals for stamina and endurance", 1),
        ("video_c", "PC Build", "install cpu motherboard ram power supply gpu", 2),
        ("video_d", "GPU Guide", "install gpu driver and benchmark performance", 3),
    ]
    for video_id, title, text, basis in videos:
        emb = _unit_vector(basis)
        repo.upsert_chunks(
            video_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=title,
            channel="Bench",
            thumbnail="",
            duration=300.0,
            transcript_source="manual_captions",
            chunks=[TranscriptChunk(0, text, 0.0, 30.0)],
            embeddings=[emb],
            embedding_model="bench",
        )

    if settings.hierarchical_retrieval_enabled:
        store = HierarchicalStore(settings)
        for video_id, title, text, emb in videos:
            capsule = MemoryCapsule(
                video_id=video_id,
                title=title,
                short_summary=text,
                topics=text.split()[:4],
            )
            store.upsert_capsule(capsule, emb)
            store.upsert_sections(
                video_id,
                [MemorySection(title="Main", summary=text, start_time=0, end_time=30)],
                [emb],
            )


def _time_import() -> float:
    import importlib

    t0 = time.perf_counter()
    importlib.import_module("app.main")
    return (time.perf_counter() - t0) * 1000


def _run_search(settings: Settings, query: str, runs: int = RUNS) -> list[float]:
    service = SearchService(settings=settings)
    timings: list[float] = []
    with patch("app.services.ahme_engine.embed_query", side_effect=_mock_embed_query):
        for _ in range(runs):
            t0 = time.perf_counter()
            service.search(query, limit=3)
            timings.append((time.perf_counter() - t0) * 1000)
    return timings


def _run_chat(settings: Settings, question: str, runs: int = RUNS) -> list[float]:
    service = ChatService(settings=settings)
    timings: list[float] = []
    with patch("app.services.ahme_engine.embed_query", side_effect=_mock_embed_query):
        for _ in range(runs):
            t0 = time.perf_counter()
            service.chat(question, top_k=4)
            timings.append((time.perf_counter() - t0) * 1000)
    return timings


def benchmark_pipeline(name: str, hierarchical: bool) -> dict:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    base = BENCH_DIR / name
    chroma_dir = base / "chroma"
    sqlite_path = base / "videos.db"
    if base.exists():
        import shutil

        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)

    settings = Settings(
        chroma_persist_dir=str(chroma_dir),
        chroma_collection_name=f"{name}_items",
        capsule_collection_name=f"{name}_capsules",
        section_collection_name=f"{name}_sections",
        sqlite_path=str(sqlite_path),
        hierarchical_retrieval_enabled=hierarchical,
        semantic_cache_enabled=True,
        debug=True,
    )
    get_settings.cache_clear()
    clear_transcript_cache()
    _seed_data(settings)

    store = HierarchicalStore(settings)
    vector_counts = store.count_vectors()

    cold_import_ms = _time_import()
    warm_import_ms = _time_import()

    simple_search = _stats(_run_search(settings, "protein meals"))
    cross_search = _stats(_run_search(settings, "compare pc build and gpu"))
    cached_search = _stats(_run_search(settings, "protein meals"))
    chat = _stats(_run_chat(settings, "What components are required for a PC build?"))

    return {
        "pipeline": "hierarchical" if hierarchical else "flat",
        "cold_import_ms": round(cold_import_ms, 2),
        "warm_import_ms": round(warm_import_ms, 2),
        "simple_search": simple_search,
        "cross_search": cross_search,
        "cached_search": cached_search,
        "chat": chat,
        "storage_bytes": _dir_size(base),
        "vectors": vector_counts,
    }


def write_report(flat: dict, hierarchical: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def row(label: str, flat_val: str, hier_val: str) -> str:
        return f"| {label} | {flat_val} | {hier_val} |"

    lines = [
        "# AHME Benchmark Report",
        "",
        f"Generated: {now}",
        "",
        "Measured on local environment with seeded in-memory Chroma/SQLite data.",
        "Median and p95 from repeated runs where enough samples were available.",
        "",
        "## Pipeline comparison",
        "",
        "| Metric | Flat pipeline | Hierarchical (AHME) |",
        "| --- | --- | --- |",
        row("Cold import (ms)", str(flat["cold_import_ms"]), str(hierarchical["cold_import_ms"])),
        row("Warm import (ms)", str(flat["warm_import_ms"]), str(hierarchical["warm_import_ms"])),
        row(
            "Simple search median (ms)",
            str(flat["simple_search"]["median_ms"]),
            str(hierarchical["simple_search"]["median_ms"]),
        ),
        row(
            "Simple search p95 (ms)",
            str(flat["simple_search"]["p95_ms"]),
            str(hierarchical["simple_search"]["p95_ms"]),
        ),
        row(
            "Cross-video search median (ms)",
            str(flat["cross_search"]["median_ms"]),
            str(hierarchical["cross_search"]["median_ms"]),
        ),
        row(
            "Repeated search median (ms)",
            str(flat["cached_search"]["median_ms"]),
            str(hierarchical["cached_search"]["median_ms"]),
        ),
        row("Chat median (ms)", str(flat["chat"]["median_ms"]), str(hierarchical["chat"]["median_ms"])),
        row("Storage bytes", str(flat["storage_bytes"]), str(hierarchical["storage_bytes"])),
        row(
            "Evidence vectors",
            str(flat["vectors"]["evidence"]),
            str(hierarchical["vectors"]["evidence"]),
        ),
        row(
            "Capsule vectors",
            str(flat["vectors"]["capsules"]),
            str(hierarchical["vectors"]["capsules"]),
        ),
        row(
            "Section vectors",
            str(flat["vectors"]["sections"]),
            str(hierarchical["vectors"]["sections"]),
        ),
        "",
        "## Notes",
        "",
        "- Ingest timing for live YouTube URLs was not measured in this offline benchmark.",
        "- LLM token usage is near-zero when `llm_provider=none` (default).",
        "- Set `HIERARCHICAL_RETRIEVAL_ENABLED=false` to revert instantly to the flat pipeline.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    print(f"Running flat pipeline benchmark ({RUNS} run(s) per case)...")
    flat = benchmark_pipeline("flat", hierarchical=False)
    print(f"Running hierarchical pipeline benchmark ({RUNS} run(s) per case)...")
    hierarchical = benchmark_pipeline("hierarchical", hierarchical=True)
    write_report(flat, hierarchical)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()

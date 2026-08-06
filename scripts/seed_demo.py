#!/usr/bin/env python3
"""Seed a small local demo library for V1 recording (no network required).

Creates UniversalMemory registry rows (titles/metadata) so Workspace lists
and trust/lifecycle demos work without live YouTube ingest.

Semantic search / chat still need real embeddings from prior ingest — this
script does **not** fake vector hits. Prefer a few real saves before Act 5–6,
or narrate the fallback path in `docs/V1_DEMO_SCRIPT.md`.

Usage:
  source .venv_clean/bin/activate
  python scripts/seed_demo.py
  python scripts/seed_demo.py --sqlite ./data/videos.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore
from app.models.lifecycle import MemoryLifecycleState
from app.models.trust import TrustMetrics, TrustTier
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SourceType

DEMO_ITEMS = [
    {
        "source_type": SourceType.YOUTUBE,
        "external_id": "demo_mcp_whiteboard",
        "canonical_url": "https://www.youtube.com/watch?v=demo_mcp_whiteboard",
        "title": "MCP servers explained on a whiteboard",
        "source_author": "Demo Channel",
        "metadata": {"demo": True, "topics": ["MCP", "agents"]},
    },
    {
        "source_type": SourceType.YOUTUBE,
        "external_id": "demo_rag_patterns",
        "canonical_url": "https://www.youtube.com/watch?v=demo_rag_patterns",
        "title": "RAG patterns for personal knowledge bases",
        "source_author": "Demo Channel",
        "metadata": {"demo": True, "topics": ["RAG", "retrieval"]},
    },
    {
        "source_type": SourceType.YOUTUBE,
        "external_id": "demo_local_llm",
        "canonical_url": "https://www.youtube.com/watch?v=demo_local_llm",
        "title": "Local LLM deployment checklist",
        "source_author": "Demo Channel",
        "metadata": {"demo": True, "topics": ["local LLM"]},
    },
    {
        "source_type": SourceType.WEB,
        "external_id": "demo_article_memory",
        "canonical_url": "https://example.com/demo/ai-memory-notes",
        "title": "Notes on intentional AI memory capture",
        "source_author": "Example",
        "metadata": {"demo": True, "topics": ["memory"]},
    },
    {
        "source_type": SourceType.GITHUB,
        "external_id": "demo/ai-memory-search-agent",
        "canonical_url": "https://github.com/example/ai-memory-search-agent",
        "title": "ai-memory-search-agent (demo repo metadata)",
        "source_author": "example",
        "metadata": {"demo": True, "topics": ["github"]},
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed V1 demo memory rows")
    parser.add_argument(
        "--sqlite",
        default=None,
        help="SQLite path (default: settings / SQLITE_PATH)",
    )
    args = parser.parse_args()

    get_settings.cache_clear()
    base = get_settings()
    settings = Settings(
        **{
            **base.model_dump(),
            **({"sqlite_path": args.sqlite} if args.sqlite else {}),
            "local_demo_mode": True,
            "auth_enabled": False,
        }
    )

    store = MemoryStore(settings)
    now = datetime.now(timezone.utc).isoformat()
    trust = TrustMetrics(
        source_reliability=0.8,
        freshness=0.9,
        verification=0.85,
        evidence_strength=0.7,
        confidence=0.8,
        overall=0.82,
        tier=TrustTier.TRUSTED,
        computed_at=now,
    )
    created = 0
    for item in DEMO_ITEMS:
        mem = store.upsert(
            user_id=LOCAL_DEFAULT_USER_ID,
            source_type=item["source_type"],
            external_id=item["external_id"],
            canonical_url=item["canonical_url"],
            title=item["title"],
            source_author=item["source_author"],
            metadata=item["metadata"],
            lifecycle_state=MemoryLifecycleState.TRUSTED,
            trust=trust,
        )
        created += 1
        print(f"  {mem.source_type.value:8}  {mem.title}  ({mem.memory_id[:8]}…)")

    print(f"\nSeeded {created} demo memories into {settings.sqlite_path}")
    print("Note: semantic search needs real embeddings — save 1–2 live videos for Acts 5–6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

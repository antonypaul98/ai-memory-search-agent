#!/usr/bin/env python3
"""Real embedded, clearly labeled offline fixtures; never use real user data."""
import os
from pathlib import Path
from app.config import get_settings
from app.core.embeddings import embed_texts
from app.db.memory_store import MemoryStore
from app.db.repositories.memory_repository import MemoryRepository
from app.db.video_registry import VideoRegistry
from app.models.lifecycle import MemoryLifecycleState
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SourceType
from app.services.fts_index import FTSIndex
from app.utils.chunking import TranscriptChunk

FIXTURES = (
  ("demo-agent-tool-recovery", "TEST DATA — Recovering From Agent Tool Failures",
   "An AI agent that receives a tool timeout should retry with exponential backoff and jitter. Limit the retry count, record the failure and its source, and surface an actionable error instead of silently inventing success. For repeated errors use a circuit breaker and keep an audit trail."),
  ("demo-rag-evidence", "TEST DATA — Retrieval With Verifiable Evidence",
   "Retrieval augmented generation searches an indexed knowledge library and provides cited source passages. Results should show where evidence came from, why it matched, and which statements cannot be proven by retrieved documents."),
)

def main():
    settings = get_settings()
    if os.getenv("MEMORY_AGENT_DEMO_E2E") != "1" or settings.auth_enabled or not settings.local_demo_mode:
        raise RuntimeError("Refusing to seed outside isolated, unauthenticated demo")
    if not all("demo-e2e" in str(Path(p).resolve()) for p in (settings.sqlite_path, settings.chroma_persist_dir)):
        raise RuntimeError("Demo requires dedicated disposable paths")
    store, repo, registry, fts = MemoryStore(settings), MemoryRepository(settings), VideoRegistry(settings), FTSIndex(settings)
    embeddings = embed_texts([body for _, _, body in FIXTURES], settings)
    if len(embeddings) != len(FIXTURES):
        raise RuntimeError("No real model embeddings generated")
    for (external_id, title, body), embedding in zip(FIXTURES, embeddings):
        url = "https://example.com/memory-agent-demo/" + external_id
        repo.upsert_chunks(
          video_id=external_id, url=url, title=title, channel="Automated fixture",
          thumbnail="", duration=None, transcript_source="offline_test_fixture",
          chunks=[TranscriptChunk(0, body, 0.0, 30.0)],
          embeddings=[embedding], embedding_model=settings.embedding_model,
          source_type=SourceType.WEB, connector_id="demo.e2e",
          user_id=LOCAL_DEFAULT_USER_ID, description="Synthetic demo fixture, not fetched")
        registry.upsert_video(video_id=external_id, url=url, title=title, channel="Automated fixture", user_id=LOCAL_DEFAULT_USER_ID)
        store.upsert(user_id=LOCAL_DEFAULT_USER_ID, source_type=SourceType.WEB,
          external_id=external_id, canonical_url=url, title=title,
          source_author="Automated fixture", lifecycle_state=MemoryLifecycleState.CAPTURED,
          metadata={"demo_fixture": True, "description_excerpt": body})
        fts.upsert(video_id=external_id, level="evidence", doc_id="demo-e2e-"+external_id,
          title=title, body=body, user_id=LOCAL_DEFAULT_USER_ID)
        print("Indexed real vector:", title, flush=True)
    assert repo.check_connection()["document_count"] >= len(FIXTURES)

if __name__ == "__main__":
    main()

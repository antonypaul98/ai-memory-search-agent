"""Hierarchical Chroma storage for capsules, sections, and evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.chroma_client import get_chroma_client
from app.models.capsule import MemoryCapsule, MemorySection
from app.utils.chunking import TranscriptChunk


class HierarchicalStore:
    """Level 1 capsules, Level 2 sections, Level 3 evidence chunks."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = get_chroma_client(self._settings)

    def _collection(self, name: str):
        return self._client.get_or_create_collection(name=name)

    def upsert_capsule(self, capsule: MemoryCapsule, embedding: list[float]) -> None:
        coll = self._collection(self._settings.capsule_collection_name)
        doc_id = f"capsule_{capsule.video_id}"
        body = f"{capsule.title}. {capsule.short_summary}. {' '.join(capsule.topics)}"
        coll.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[body],
            metadatas=[{
                "video_id": capsule.video_id,
                "level": "capsule",
                "doc_id": doc_id,
                "title": capsule.title,
                "creator": capsule.creator,
                "user_goal": capsule.user_goal,
                "save_reason": capsule.save_reason,
                "capsule_json": capsule.model_dump_json(),
            }],
        )

    def upsert_sections(
        self,
        video_id: str,
        sections: list[MemorySection],
        embeddings: list[list[float]],
    ) -> None:
        if not sections:
            return
        coll = self._collection(self._settings.section_collection_name)
        ids = []
        docs = []
        metas = []
        for idx, (section, emb) in enumerate(zip(sections, embeddings)):
            doc_id = f"section_{video_id}_{idx}"
            ids.append(doc_id)
            docs.append(f"{section.title}. {section.summary}")
            metas.append({
                "video_id": video_id,
                "level": "section",
                "doc_id": doc_id,
                "section_index": idx,
                "title": section.title,
                "start_time": section.start_time,
                "end_time": section.end_time,
            })
        coll.upsert(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)

    def search_level(
        self,
        collection_name: str,
        query_embedding: list[float],
        *,
        top_k: int,
        video_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        coll = self._collection(collection_name)
        if coll.count() == 0:
            return []
        where = {"video_id": {"$in": video_ids}} if video_ids else None
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, coll.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        try:
            results = coll.query(**kwargs)
        except Exception:
            return []
        hits = []
        docs = results.get("documents") or [[]]
        metas = results.get("metadatas") or [[]]
        dists = results.get("distances") or [[]]
        for doc, meta, dist in zip(docs[0], metas[0], dists[0]):
            if not meta:
                continue
            hits.append({
                "matched_text": doc or "",
                "video_id": meta.get("video_id", ""),
                "title": meta.get("title", ""),
                "relevance_score": max(0.0, 1.0 - float(dist)),
                "level": meta.get("level", ""),
                "doc_id": meta.get("doc_id") or "",
                "section_index": meta.get("section_index"),
                "start_time": meta.get("start_time"),
                "end_time": meta.get("end_time"),
            })
        return hits

    def delete_video(self, video_id: str) -> None:
        for name in (
            self._settings.capsule_collection_name,
            self._settings.section_collection_name,
        ):
            coll = self._collection(name)
            try:
                coll.delete(where={"video_id": video_id})
            except Exception:
                pass

    def count_vectors(self) -> dict[str, int]:
        return {
            "capsules": self._collection(self._settings.capsule_collection_name).count(),
            "sections": self._collection(self._settings.section_collection_name).count(),
            "evidence": self._collection(self._settings.chroma_collection_name).count(),
        }


def store_capsule_json(settings: Settings, video_id: str, capsule: MemoryCapsule) -> None:
    from app.db.schema import get_connection, migrate

    migrate(settings)
    with get_connection(settings) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_capsules_json (video_id, capsule_json, updated_at)
            VALUES (?, ?, ?)
            """,
            (video_id, capsule.model_dump_json(), datetime.now(timezone.utc).isoformat()),
        )

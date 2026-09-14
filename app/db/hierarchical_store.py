"""Hierarchical Chroma storage for capsules, sections, and evidence."""

from __future__ import annotations

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

    @staticmethod
    def _doc_id(level: str, video_id: str, *, user_id: str | None = None, index: int | None = None) -> str:
        """Return a tenant-safe vector id while preserving legacy local ids when unscoped."""
        parts = [level]
        if user_id:
            parts.append(user_id)
        parts.append(video_id)
        if index is not None:
            parts.append(str(index))
        return "_".join(parts)

    @staticmethod
    def _where(*, user_id: str | None = None, video_ids: list[str] | None = None, video_id: str | None = None):
        clauses: list[dict[str, Any]] = []
        if user_id:
            clauses.append({"user_id": user_id})
        if video_id:
            clauses.append({"video_id": video_id})
        elif video_ids:
            clauses.append({"video_id": {"$in": video_ids}})
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def upsert_capsule(
        self,
        capsule: MemoryCapsule,
        embedding: list[float],
        *,
        user_id: str | None = None,
    ) -> None:
        coll = self._collection(self._settings.capsule_collection_name)
        doc_id = self._doc_id("capsule", capsule.video_id, user_id=user_id)
        body = f"{capsule.title}. {capsule.short_summary}. {' '.join(capsule.topics)}"
        metadata: dict[str, Any] = {
            "video_id": capsule.video_id,
            "level": "capsule",
            "doc_id": doc_id,
            "title": capsule.title,
            "creator": capsule.creator,
            "user_goal": capsule.user_goal,
            "save_reason": capsule.save_reason,
            "capsule_json": capsule.model_dump_json(),
        }
        if user_id:
            metadata["user_id"] = user_id
        coll.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[body],
            metadatas=[metadata],
        )

    def upsert_sections(
        self,
        video_id: str,
        sections: list[MemorySection],
        embeddings: list[list[float]],
        *,
        user_id: str | None = None,
    ) -> None:
        if not sections:
            return
        coll = self._collection(self._settings.section_collection_name)
        ids = []
        docs = []
        metas = []
        for idx, (section, emb) in enumerate(zip(sections, embeddings)):
            doc_id = self._doc_id("section", video_id, user_id=user_id, index=idx)
            ids.append(doc_id)
            docs.append(f"{section.title}. {section.summary}")
            metadata: dict[str, Any] = {
                "video_id": video_id,
                "level": "section",
                "doc_id": doc_id,
                "section_index": idx,
                "title": section.title,
                "start_time": section.start_time,
                "end_time": section.end_time,
            }
            if user_id:
                metadata["user_id"] = user_id
            metas.append(metadata)
        coll.upsert(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)

    def search_level(
        self,
        collection_name: str,
        query_embedding: list[float],
        *,
        top_k: int,
        video_ids: list[str] | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        coll = self._collection(collection_name)
        if coll.count() == 0:
            return []
        where = self._where(user_id=user_id, video_ids=video_ids)
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
                "user_id": meta.get("user_id"),
            })
        return hits

    def delete_video(self, video_id: str, *, user_id: str | None = None) -> None:
        for name in (
            self._settings.capsule_collection_name,
            self._settings.section_collection_name,
        ):
            coll = self._collection(name)
            try:
                coll.delete(where=self._where(user_id=user_id, video_id=video_id))
            except Exception:
                pass

    def legacy_unscoped_vector_ids(self) -> dict[str, list[str]]:
        """Return legacy capsule/section ids that have no trustworthy tenant owner.

        Older hierarchical vectors predate tenant metadata. They must never be
        auto-attributed to a tenant because the vector record itself contains no
        ownership proof. Callers can preview this inventory and either leave it
        untouched or explicitly purge it before regenerating vectors from
        tenant-owned canonical data.
        """
        result: dict[str, list[str]] = {"capsules": [], "sections": []}
        for key, name in (
            ("capsules", self._settings.capsule_collection_name),
            ("sections", self._settings.section_collection_name),
        ):
            coll = self._collection(name)
            try:
                rows = coll.get(include=["metadatas"])
            except Exception:
                continue
            ids = rows.get("ids") or []
            metadatas = rows.get("metadatas") or []
            for vector_id, metadata in zip(ids, metadatas):
                owner = (metadata or {}).get("user_id")
                if not isinstance(owner, str) or not owner.strip():
                    result[key].append(str(vector_id))
        return result

    def purge_legacy_unscoped_vectors(self, *, confirm: bool = False) -> dict[str, int]:
        """Delete only legacy unscoped capsule/section vectors after confirmation."""
        if not confirm:
            raise ValueError("explicit confirm=True is required to purge legacy unscoped vectors")

        legacy = self.legacy_unscoped_vector_ids()
        deleted: dict[str, int] = {"capsules": 0, "sections": 0}
        for key, name in (
            ("capsules", self._settings.capsule_collection_name),
            ("sections", self._settings.section_collection_name),
        ):
            ids = legacy[key]
            if not ids:
                continue
            self._collection(name).delete(ids=ids)
            deleted[key] = len(ids)
        return deleted

    def count_vectors(self) -> dict[str, int]:
        return {
            "capsules": self._collection(self._settings.capsule_collection_name).count(),
            "sections": self._collection(self._settings.section_collection_name).count(),
            "evidence": self._collection(self._settings.chroma_collection_name).count(),
        }

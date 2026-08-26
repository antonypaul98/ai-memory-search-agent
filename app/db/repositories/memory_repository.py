"""
ChromaDB repository for memory items.

All database access for saved content flows through this class.
Routes and services must NOT import chroma_client directly.
"""

from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.core.exceptions import ChromaConnectionError
from app.db.chroma_client import get_collection
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SourceType
from app.services.enrichment_service import deserialize_string_list, serialize_string_list
from app.utils.chunking import TranscriptChunk


class MemoryRepository:
    """Read/write access to the Chroma memory_items collection."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def check_connection(self) -> dict:
        try:
            collection = get_collection(self._settings)
            document_count = collection.count()
        except Exception as exc:
            raise ChromaConnectionError(f"Failed to connect to ChromaDB: {exc}") from exc
        return {
            "connected": True,
            "collection": self._settings.chroma_collection_name,
            "persist_dir": self._settings.chroma_persist_dir,
            "document_count": document_count,
        }

    def upsert_chunks(
        self,
        *,
        video_id: str,
        url: str,
        title: str,
        channel: str,
        thumbnail: str,
        duration: float | None,
        transcript_source: str,
        chunks: list[TranscriptChunk],
        embeddings: list[list[float]],
        embedding_model: str,
        description: str = "",
        one_line_memory: str = "",
        why_saved: list[str] | None = None,
        action_items: list[str] | None = None,
        user_id: str = LOCAL_DEFAULT_USER_ID,
        language: str | None = None,
        channel_id: str = "",
        published_at: str | None = None,
        tags: list[str] | None = None,
        categories: list[str] | None = None,
        playlist_id: str | None = None,
        source_type: SourceType = SourceType.YOUTUBE,
        connector_id: str = "youtube.v1",
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length must match")
        if not chunks:
            return 0

        self.delete_item(video_id, user_id=user_id)
        collection = get_collection(self._settings)
        created_at = datetime.now(timezone.utc).isoformat()
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        why_saved = why_saved or []
        action_items = action_items or []
        tags = tags or []
        categories = categories or []
        source_value = source_type.value if isinstance(source_type, SourceType) else str(source_type)

        for chunk in chunks:
            doc_id = f"{source_value}_{user_id}_{video_id}_{chunk.chunk_index}"
            ids.append(doc_id)
            documents.append(chunk.text)
            page_number = int(chunk.start_time_sec) if source_type == SourceType.PDF and chunk.start_time_sec >= 1 else 0
            metadatas.append({
                "source_type": source_value,
                "connector_id": connector_id,
                "user_id": user_id,
                "video_id": video_id,
                "item_id": video_id,
                "url": url,
                "title": title,
                "channel": channel,
                "source_author": channel,
                "thumbnail": thumbnail,
                "duration": duration if duration is not None else -1.0,
                "chunk_index": chunk.chunk_index,
                "start_time": chunk.start_time_sec,
                "end_time": chunk.end_time_sec,
                "page_number": page_number,
                "transcript_source": transcript_source,
                "embedding_model": embedding_model,
                "created_at": created_at,
                "description": description,
                "one_line_memory": one_line_memory,
                "why_saved": serialize_string_list(why_saved),
                "action_items": serialize_string_list(action_items),
                "channel_id": channel_id or "",
                "language": language or "",
                "published_at": published_at or "",
                "tags": serialize_string_list(tags),
                "categories": serialize_string_list(categories),
                "playlist_id": playlist_id or "",
                "transcript_available": True,
            })

        collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        return len(chunks)

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        *,
        user_id: str = LOCAL_DEFAULT_USER_ID,
    ) -> list[dict[str, Any]]:
        """Query nearest chunks while enforcing tenant scope in Chroma itself.

        Non-default users are always queried with an explicit `user_id` metadata
        filter. The local demo user keeps a compatibility fallback for legacy
        chunks created before `user_id` metadata existed; those fallback results
        are still post-filtered and can never be returned to another user.
        """
        collection = get_collection(self._settings)
        count = collection.count()
        if count == 0:
            return []

        n_results = min(max(top_k * 4, top_k), count)
        query_kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
            "where": {"user_id": user_id},
        }
        try:
            results = collection.query(**query_kwargs)
        except Exception:
            if user_id != LOCAL_DEFAULT_USER_ID:
                raise
            # Compatibility only for pre-migration local data whose metadata has
            # no user_id. Never use this unscoped path for authenticated tenants.
            query_kwargs.pop("where", None)
            results = collection.query(**query_kwargs)

        hits: list[dict[str, Any]] = []
        documents = results.get("documents") or [[]]
        metadatas = results.get("metadatas") or [[]]
        distances = results.get("distances") or [[]]

        for doc, meta, distance in zip(documents[0], metadatas[0], distances[0]):
            if meta is None or not _metadata_belongs_to_user(meta, user_id):
                continue
            relevance_score = max(0.0, 1.0 - float(distance))
            hits.append({
                "matched_text": doc or "",
                "video_id": meta.get("video_id") or meta.get("item_id", ""),
                "title": meta.get("title", ""),
                "channel": meta.get("channel") or meta.get("source_author", ""),
                "thumbnail": meta.get("thumbnail", ""),
                "url": meta.get("url", ""),
                "description": meta.get("description", ""),
                "one_line_memory": meta.get("one_line_memory", ""),
                "why_saved": deserialize_string_list(meta.get("why_saved")),
                "action_items": deserialize_string_list(meta.get("action_items")),
                "duration": _optional_duration(meta.get("duration")),
                "start_time": _optional_float(meta.get("start_time")),
                "end_time": _optional_float(meta.get("end_time")),
                "relevance_score": relevance_score,
                "source_type": meta.get("source_type", "youtube"),
                "connector_id": meta.get("connector_id", "youtube.v1"),
                "page_number": meta.get("page_number") or 0,
                "created_at": meta.get("created_at"),
                "language": meta.get("language") or None,
                "channel_id": meta.get("channel_id") or "",
                "published_at": meta.get("published_at") or None,
                "tags": deserialize_string_list(meta.get("tags")),
                "transcript_available": bool(meta.get("transcript_available", True)),
            })
            if len(hits) >= top_k:
                break
        return hits[:top_k]

    def delete_item(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> None:
        collection = get_collection(self._settings)
        try:
            collection.delete(where={"$and": [{"video_id": video_id}, {"user_id": user_id}]})
        except Exception:
            if user_id == LOCAL_DEFAULT_USER_ID:
                try:
                    collection.delete(where={"video_id": video_id})
                except Exception:
                    pass

    def video_exists(self, video_id: str, *, user_id: str = LOCAL_DEFAULT_USER_ID) -> bool:
        collection = get_collection(self._settings)
        try:
            result = collection.get(where={"$and": [{"video_id": video_id}, {"user_id": user_id}]}, limit=1, include=[])
            ids = result.get("ids") or []
            if ids:
                return True
            if user_id == LOCAL_DEFAULT_USER_ID:
                result = collection.get(where={"video_id": video_id}, limit=1, include=["metadatas"])
                metas = result.get("metadatas") or []
                if metas and metas[0]:
                    return _metadata_belongs_to_user(metas[0], user_id)
            return False
        except Exception:
            return False


def _metadata_belongs_to_user(meta: dict[str, Any], user_id: str) -> bool:
    stored = meta.get("user_id")
    if not stored:
        return user_id == LOCAL_DEFAULT_USER_ID
    return str(stored) == user_id


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_duration(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is None or parsed < 0:
        return None
    return parsed

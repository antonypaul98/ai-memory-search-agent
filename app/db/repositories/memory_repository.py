"""
ChromaDB repository for memory items.

All database access for saved content flows through this class.
Routes and services must NOT import chroma_client directly.

Phase 2: check_connection() only (used by health endpoint).
Phase 3+: upsert_chunks(), search(), delete_item()
"""

from app.config import Settings, get_settings
from app.core.exceptions import ChromaConnectionError
from app.db.chroma_client import get_collection


class MemoryRepository:
    """
    Read/write access to the Chroma memory_items collection.

    When upserting in Phase 3+, every chunk must include MemoryMetadata fields,
    including optional embedding_model, content_hash, published_at, platform_metadata.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def check_connection(self) -> dict:
        """
        Verify ChromaDB is reachable and return collection stats.

        Returns a dict consumed by HealthService — not a Pydantic model,
        so the service layer can map it to HealthResponse.
        """
        try:
            collection = get_collection(self._settings)
            document_count = collection.count()
        except Exception as exc:
            raise ChromaConnectionError(
                f"Failed to connect to ChromaDB: {exc}"
            ) from exc

        return {
            "connected": True,
            "collection": self._settings.chroma_collection_name,
            "persist_dir": self._settings.chroma_persist_dir,
            "document_count": document_count,
        }

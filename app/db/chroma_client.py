"""
ChromaDB Persistent Client setup.

Wraps chromadb.PersistentClient so the rest of the app never imports
Chroma directly. Data is stored on disk at settings.chroma_persist_dir.
"""

import os
from typing import TYPE_CHECKING

import chromadb

from app.config import Settings, get_settings

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection

# Cache clients by persist path (Settings objects are not hashable for lru_cache).
_clients: dict[str, chromadb.PersistentClient] = {}


def get_chroma_client(settings: Settings | None = None) -> chromadb.PersistentClient:
    """
    Return a Chroma PersistentClient for the configured persist directory.

    Creates the persist directory if it does not exist yet.
    PersistentClient saves all vectors to disk — data survives restarts.
    """
    settings = settings or get_settings()
    persist_dir = settings.chroma_persist_dir

    if persist_dir not in _clients:
        os.makedirs(persist_dir, exist_ok=True)
        _clients[persist_dir] = chromadb.PersistentClient(path=persist_dir)

    return _clients[persist_dir]


def get_collection(settings: Settings | None = None) -> "Collection":
    """
    Return the configured Chroma collection, creating it if needed.

    Phase 2: collection stays empty (no upserts yet).
    Phase 3+: chunks with MemoryMetadata will be stored here.
    """
    settings = settings or get_settings()
    client = get_chroma_client(settings)
    return client.get_or_create_collection(name=settings.chroma_collection_name)


def reset_chroma_cache() -> None:
    """Clear cached clients — used in tests to pick up new settings."""
    _clients.clear()

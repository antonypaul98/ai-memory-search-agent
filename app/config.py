"""
Application configuration loaded from environment variables.

Uses pydantic-settings so all config lives in one typed Settings class.
Values are read from .env and can be overridden in tests via dependency injection.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the entire application.

    Every module that needs config should call get_settings() rather than
    reading os.environ directly — this keeps settings consistent and testable.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "AI Memory Search Agent"
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # --- ChromaDB (Persistent Client stores data on disk) ---
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "memory_items"

    # --- SQLite registry (Phase 3+) ---
    sqlite_path: str = "./data/videos.db"

    # --- Embeddings (Phase 3+) ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Chunking (Phase 3+) ---
    chunk_size: int = 500
    chunk_overlap: int = 50

    # --- Search (Phase 4+) ---
    search_top_k_chunks: int = 30
    search_top_k_videos: int = 10

    # --- Streamlit (Phase 5+) ---
    fastapi_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance (singleton).

    @lru_cache ensures we only parse .env once per process.
    Tests can clear this cache and inject alternate settings.
    """
    return Settings()

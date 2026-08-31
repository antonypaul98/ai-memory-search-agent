"""
Application configuration loaded from environment variables.

Uses pydantic-settings so all config lives in one typed Settings class.
Values are read from .env and can be overridden in tests via dependency injection.
"""

from functools import lru_cache
from typing import Literal

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

    # --- Ingest ---
    ingest_concurrency: int = 3
    embedding_batch_size: int = 32
    ingest_metadata_timeout_sec: int = 60
    ingest_transcript_timeout_sec: int = 120

    # --- Adaptive Hierarchical Memory Engine (AHME) ---
    hierarchical_retrieval_enabled: bool = True
    capsule_collection_name: str = "memory_capsules"
    section_collection_name: str = "memory_sections"
    capsule_top_k: int = 8
    video_top_k: int = 4
    section_top_k: int = 6
    evidence_top_k: int = 8
    rrf_k: int = 60
    mmr_lambda: float = 0.7
    semantic_cache_enabled: bool = True
    semantic_cache_ttl_sec: int = 3600
    semantic_cache_similarity_threshold: float = 0.92
    transcript_artifact_dir: str = "./data/transcripts"
    schema_version: int = 9

    # --- Distribution & capture layer ---
    pwa_enabled: bool = True
    auth_enabled: bool = False
    local_demo_mode: bool = True
    auth_secret_env: str = "AUTH_SECRET"
    session_ttl_hours: int = 168
    # GAP-02 relational cutover is explicit per store. SQLite remains the safe
    # default until the full production profile and migration path are validated.
    auth_store_backend: Literal["sqlite", "postgres"] = "sqlite"
    # Canonical memory/provenance/lifecycle persistence. Postgres selection is
    # explicit and fail-closed; SQLite remains the safe self-host default.
    memory_store_backend: Literal["sqlite", "postgres"] = "sqlite"
    # Capture request/status persistence follows the same explicit production
    # cutover contract; this does not yet move bookmark/import-run state.
    capture_store_backend: Literal["sqlite", "postgres"] = "sqlite"
    jobs_enabled: bool = True
    # F-35/GAP-01: keep the historical single-process behavior by default,
    # while allowing API-only processes to avoid spawning duplicate workers.
    worker_mode: Literal["api", "worker", "all"] = "all"
    job_worker_concurrency: int = 2
    job_lease_seconds: int = 120
    job_poll_interval_sec: float = 2.0
    # GAP-02 durable job state. SQLite remains the safe default until the
    # application/backend cutover and Postgres E2E validation are complete.
    job_store_backend: Literal["sqlite", "postgres"] = "sqlite"
    postgres_dsn_env: str = "DATABASE_URL"
    postgres_connect_timeout_sec: int = 10
    # F-35 wake transport is independent from the durable job store backend.
    job_queue_backend: Literal["sqlite", "redis"] = "sqlite"
    redis_url_env: str = "REDIS_URL"
    redis_queue_name: str = "memory-agent:jobs:wakeup"
    redis_block_timeout_sec: int = 5
    youtube_api_key_env: str = "YOUTUBE_API_KEY"
    connector_token_key_env: str = "CONNECTOR_TOKEN_KEY"
    # Optional comma-separated connector allowlist. Empty keeps all built-ins enabled.
    connector_enabled_ids: str = ""
    playlist_page_size: int = 50
    playlist_max_videos: int = 500
    capture_max_response_bytes: int = 2_000_000
    capture_fetch_timeout_sec: int = 15
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,chrome-extension://"
    trusted_hosts: str = "*"
    max_request_body_bytes: int = 1_048_576

    # --- Rate limiting (V1-8 / P-02) ---
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_sec: int = 60
    rate_limit_auth_requests: int = 20
    rate_limit_auth_window_sec: int = 60

    # --- Optional LLM (no credentials hard-coded) ---
    llm_provider: str = "none"  # none | ollama | openai_compatible | router
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = ""
    llm_api_key_env: str = "OPENAI_API_KEY"
    llm_timeout_sec: int = 60

    # --- Model Router / pooled BYO free-tier capacity ---
    model_router_enabled: bool = True
    # JSON array of provider/model metadata. API keys are referenced by env-var name only.
    model_router_catalog_json: str = ""
    model_router_cooldown_sec: int = 60
    # Optional exact route ID or model ID used by the internal LLM provider when LLM_PROVIDER=router.
    model_router_pinned_model: str = ""

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

"""Production relational-storage profile helpers.

These helpers are importable by runtime services and validation scripts. They
only describe whether durable relational stores are configured for Postgres;
they do not prove connectivity or zero-SQLite-write behavior by themselves.
"""

from __future__ import annotations

from app.config import Settings


RELATIONAL_STORE_BACKEND_FIELDS = (
    "auth_store_backend",
    "memory_store_backend",
    "capture_store_backend",
    "bookmark_store_backend",
    "fts_store_backend",
    "semantic_cache_store_backend",
    "youtube_store_backend",
    "job_store_backend",
)


def production_storage_profile_errors(settings: Settings) -> list[str]:
    """Return deterministic errors for an incomplete Postgres production profile."""
    errors: list[str] = []
    for field in RELATIONAL_STORE_BACKEND_FIELDS:
        value = getattr(settings, field)
        if value != "postgres":
            errors.append(f"{field} must be 'postgres' for the production profile; got {value!r}")
    if not settings.postgres_dsn_env.strip():
        errors.append("postgres_dsn_env must name the environment variable containing the Postgres DSN")
    return errors


def is_complete_postgres_profile(settings: Settings) -> bool:
    """Return True only when the complete durable relational profile is Postgres-ready."""
    return not production_storage_profile_errors(settings)


def validate_production_storage_profile(settings: Settings) -> None:
    """Raise ValueError when the configured production profile is incomplete."""
    errors = production_storage_profile_errors(settings)
    if errors:
        raise ValueError("Invalid production relational-storage profile:\n- " + "\n- ".join(errors))

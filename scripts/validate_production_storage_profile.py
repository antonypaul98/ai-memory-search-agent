"""Validate that a production relational-storage profile is fully on Postgres.

This is a configuration guard for P-03. It does not prove runtime zero-write
behavior or connectivity to a real Postgres instance; those remain separate
acceptance checks.
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
    """Return deterministic errors for relational stores not using Postgres."""
    errors: list[str] = []
    for field in RELATIONAL_STORE_BACKEND_FIELDS:
        value = getattr(settings, field)
        if value != "postgres":
            errors.append(f"{field} must be 'postgres' for the production profile; got {value!r}")
    if not settings.postgres_dsn_env.strip():
        errors.append("postgres_dsn_env must name the environment variable containing the Postgres DSN")
    return errors


def validate_production_storage_profile(settings: Settings) -> None:
    """Raise ValueError when the configured production profile is incomplete."""
    errors = production_storage_profile_errors(settings)
    if errors:
        raise ValueError("Invalid production relational-storage profile:\n- " + "\n- ".join(errors))


if __name__ == "__main__":
    validate_production_storage_profile(Settings())
    print("Production relational-storage profile selects Postgres for every durable relational store.")

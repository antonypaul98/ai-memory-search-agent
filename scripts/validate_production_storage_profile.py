"""Validate that a production relational-storage profile is fully on Postgres.

This is a configuration guard for P-03. It does not prove runtime zero-write
behavior or connectivity to a real Postgres instance; those remain separate
acceptance checks.
"""

from __future__ import annotations

from app.config import Settings
from app.db.production_storage_profile import (
    RELATIONAL_STORE_BACKEND_FIELDS,
    is_complete_postgres_profile,
    production_storage_profile_errors,
    validate_production_storage_profile,
)

__all__ = (
    "RELATIONAL_STORE_BACKEND_FIELDS",
    "is_complete_postgres_profile",
    "production_storage_profile_errors",
    "validate_production_storage_profile",
)


if __name__ == "__main__":
    validate_production_storage_profile(Settings())
    print("Production relational-storage profile selects Postgres for every durable relational store.")

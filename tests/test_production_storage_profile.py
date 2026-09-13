from app.config import Settings
from scripts.validate_production_storage_profile import (
    RELATIONAL_STORE_BACKEND_FIELDS,
    production_storage_profile_errors,
    validate_production_storage_profile,
)


def _production_settings(**overrides):
    values = {field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_storage_profile_accepts_all_postgres_backends():
    settings = _production_settings(postgres_dsn_env="DATABASE_URL")

    assert production_storage_profile_errors(settings) == []
    validate_production_storage_profile(settings)


def test_production_storage_profile_reports_every_sqlite_backend_deterministically():
    settings = _production_settings(
        auth_store_backend="sqlite",
        semantic_cache_store_backend="sqlite",
    )

    assert production_storage_profile_errors(settings) == [
        "auth_store_backend must be 'postgres' for the production profile; got 'sqlite'",
        "semantic_cache_store_backend must be 'postgres' for the production profile; got 'sqlite'",
    ]


def test_production_storage_profile_rejects_missing_dsn_environment_name():
    settings = _production_settings(postgres_dsn_env="   ")

    assert production_storage_profile_errors(settings) == [
        "postgres_dsn_env must name the environment variable containing the Postgres DSN"
    ]

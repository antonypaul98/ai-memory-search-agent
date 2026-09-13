from app.config import Settings
from app.db.production_storage_profile import (
    RELATIONAL_STORE_BACKEND_FIELDS,
    is_complete_postgres_profile,
)


def _settings(**overrides):
    values = {field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS}
    values["postgres_dsn_env"] = "DATABASE_URL"
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_complete_postgres_profile_is_runtime_safe_to_identify():
    assert is_complete_postgres_profile(_settings()) is True


def test_runtime_profile_helper_rejects_residual_sqlite_backend():
    assert is_complete_postgres_profile(_settings(memory_store_backend="sqlite")) is False


def test_runtime_profile_helper_requires_dsn_indirection():
    assert is_complete_postgres_profile(_settings(postgres_dsn_env="   ")) is False

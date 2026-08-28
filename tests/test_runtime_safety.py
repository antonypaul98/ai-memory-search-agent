import pytest

from app.config import Settings
from app.db.runtime_safety import UnsafeRuntimeTopology, validate_runtime_topology


def test_single_node_default_is_allowed():
    validate_runtime_topology(Settings())


def test_sqlite_polling_split_mode_is_allowed_for_non_redis_local_operation():
    validate_runtime_topology(Settings(worker_mode="worker", job_queue_backend="sqlite"))


def test_disabled_jobs_bypass_topology_gate():
    validate_runtime_topology(
        Settings(jobs_enabled=False, worker_mode="worker", job_queue_backend="redis")
    )


@pytest.mark.parametrize("worker_mode", ["api", "worker"])
def test_split_redis_runtime_fails_closed_until_postgres_cutover(worker_mode):
    settings = Settings(worker_mode=worker_mode, job_queue_backend="redis")

    with pytest.raises(UnsafeRuntimeTopology) as exc:
        validate_runtime_topology(settings)

    message = str(exc.value)
    assert "GAP-02" in message
    assert "Postgres" in message
    assert "SQLite" in message


def test_single_process_redis_transport_remains_testable():
    validate_runtime_topology(Settings(worker_mode="all", job_queue_backend="redis"))

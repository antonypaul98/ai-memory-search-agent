import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.job_worker import JobWorker, should_start_job_worker


def test_worker_mode_defaults_to_all_for_backward_compatibility():
    settings = Settings(_env_file=None)

    assert settings.worker_mode == "all"
    assert should_start_job_worker(settings) is settings.jobs_enabled


def test_api_mode_never_starts_background_worker_threads(monkeypatch):
    settings = Settings(_env_file=None, jobs_enabled=True, worker_mode="api", job_worker_concurrency=3)
    worker = JobWorker(settings)

    started = []
    monkeypatch.setattr("threading.Thread.start", lambda self: started.append(self.name))

    worker.start()

    assert started == []
    assert worker._threads == []


@pytest.mark.parametrize("mode", ["worker", "all"])
def test_worker_capable_modes_are_allowed_when_jobs_enabled(mode):
    settings = Settings(_env_file=None, jobs_enabled=True, worker_mode=mode)

    assert should_start_job_worker(settings) is True


def test_jobs_disabled_overrides_worker_mode():
    settings = Settings(_env_file=None, jobs_enabled=False, worker_mode="worker")

    assert should_start_job_worker(settings) is False


def test_unknown_worker_mode_fails_closed_at_configuration_boundary():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, worker_mode="surprise")

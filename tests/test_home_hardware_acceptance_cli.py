from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.home_agent import hardware_acceptance_cli as cli


def test_validation_rejects_physical_camera_without_explicit_opt_in():
    with pytest.raises(ValueError, match="physical camera access is disabled"):
        cli.validate_config(
            session_id="s",
            user_id="u",
            source_id="cam",
            location="home",
            device_index=0,
            max_frames=3,
            confirmations=2,
            min_interval_seconds=1.0,
            min_confidence=0.8,
            require_event=True,
            allow_physical_camera=False,
        )


def test_validation_requires_extra_frame_for_event_confirmation():
    with pytest.raises(ValueError, match="max_frames >= confirmations + 1"):
        cli.validate_config(
            session_id="s",
            user_id="u",
            source_id="cam",
            location="home",
            device_index=0,
            max_frames=2,
            confirmations=2,
            min_interval_seconds=1.0,
            min_confidence=0.8,
            require_event=True,
            allow_physical_camera=True,
        )


def test_validation_rejects_invalid_configuration_before_factory():
    with pytest.raises(ValueError, match="max_frames must be >= 1"):
        cli.validate_config(
            session_id="s",
            user_id="u",
            source_id="cam",
            location="home",
            device_index=0,
            max_frames=0,
            confirmations=2,
            min_interval_seconds=1.0,
            min_confidence=0.8,
            require_event=False,
            allow_physical_camera=True,
        )


def test_run_cli_uses_injected_capture_and_never_constructs_a_camera_directly(monkeypatch):
    called = {"factory": 0, "smoke": 0}

    class FakeResult:
        passed = True

    fake_capture = object()

    def factory():
        called["factory"] += 1
        return fake_capture

    def fake_smoke(**kwargs):
        called["smoke"] += 1
        assert kwargs["capture"] is fake_capture
        assert kwargs["max_frames"] == 3
        assert kwargs["confirmations"] == 2
        assert kwargs["require_event"] is True
        return FakeResult()

    monkeypatch.setattr(cli, "run_hardware_smoke", fake_smoke)
    result = cli.run_cli(
        capture_factory=factory,
        session_id="s",
        user_id="u",
        source_id="cam",
        location="home",
        device_index=0,
        max_frames=3,
        confirmations=2,
        min_interval_seconds=1.0,
        min_confidence=0.8,
        require_event=True,
    )
    assert result.passed is True
    assert called == {"factory": 1, "smoke": 1}


def test_cli_validation_does_not_load_factory_without_physical_opt_in(monkeypatch):
    loaded = []

    def fail_load(_):
        loaded.append(True)
        raise AssertionError("factory must not load during rejected configuration")

    monkeypatch.setattr(cli, "load_capture_factory", fail_load)
    assert cli.main([
        "--capture-factory", "does.not.matter:factory",
        "--session-id", "s",
        "--user-id", "u",
        "--source-id", "cam",
        "--location", "home",
    ]) == 2
    assert loaded == []

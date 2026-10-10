from __future__ import annotations

import json

from types import SimpleNamespace

import pytest

from app.services.home_agent import hardware_acceptance_cli as cli


def test_validation_rejects_physical_camera_without_explicit_opt_in():
    with pytest.raises(ValueError, match="physical camera access requires explicit opt-in"):
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
    with pytest.raises(ValueError, match=r"max_frames >= confirmations \+ 1"):
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


def test_validation_rejects_physical_acceptance_without_required_event():
    with pytest.raises(ValueError, match="requires --require-event"):
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
            require_event=False,
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
        allow_physical_camera=True,
    )
    assert result.passed is True
    assert called == {"factory": 1, "smoke": 1}



@pytest.mark.parametrize("flag,bad_value", [
    ("allow_physical_camera", False),
    ("allow_physical_camera", 1),
    ("allow_physical_camera", "true"),
    ("require_event", False),
    ("require_event", 1),
    ("require_event", "true"),
])
def test_direct_runner_rejects_missing_or_invalid_consent_before_factory(flag, bad_value):
    constructed = []

    def factory():
        constructed.append(True)
        raise AssertionError("capture factory must not run without strict consent")

    config = dict(
        session_id="session", user_id="tenant", source_id="camera", location="kitchen",
        device_index=0, max_frames=3, confirmations=2,
        min_interval_seconds=1.0, min_confidence=0.8,
        require_event=True, allow_physical_camera=True,
    )
    config[flag] = bad_value
    with pytest.raises(ValueError):
        cli.run_cli(factory, **config)
    assert constructed == []


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


def test_cli_rejects_missing_event_requirement_before_loading_factory(monkeypatch):
    loaded = []

    def fail_load(_):
        loaded.append(True)
        raise AssertionError("factory must not load when --require-event is missing")

    monkeypatch.setattr(cli, "load_capture_factory", fail_load)
    assert cli.main([
        "--capture-factory", "does.not.matter:factory",
        "--session-id", "s",
        "--user-id", "u",
        "--source-id", "cam",
        "--location", "home",
        "--allow-physical-camera",
    ]) == 2
    assert loaded == []


@pytest.mark.parametrize("flag,value", [
    ("--min-interval-seconds", "nan"),
    ("--min-interval-seconds", "inf"),
    ("--min-interval-seconds", "-inf"),
    ("--min-confidence", "nan"),
    ("--min-confidence", "inf"),
    ("--min-confidence", "-inf"),
])
def test_cli_rejects_nonfinite_numbers_before_loading_factory(monkeypatch, flag, value):
    loaded = []

    def fail_load(_):
        loaded.append(True)
        raise AssertionError("camera factory must not load for nonfinite configuration")

    monkeypatch.setattr(cli, "load_capture_factory", fail_load)
    assert cli.main([
        "--capture-factory", "does.not.matter:factory",
        "--session-id", "s",
        "--user-id", "u",
        "--source-id", "cam",
        "--location", "home",
        "--allow-physical-camera",
        "--require-event",
        f"{flag}={value}",
    ]) == 2
    assert loaded == []

@pytest.mark.parametrize("value", ["1e308", "0.0000001"])
def test_cli_rejects_unrepresentable_intervals_before_loading_factory(monkeypatch, value):
    loaded = []

    def fail_load(_):
        loaded.append(True)
        raise AssertionError("camera factory must not load for invalid interval")

    monkeypatch.setattr(cli, "load_capture_factory", fail_load)
    assert cli.main([
        "--capture-factory", "does.not.matter:factory",
        "--session-id", "s", "--user-id", "u",
        "--source-id", "cam", "--location", "home",
        "--allow-physical-camera", "--require-event",
        f"--min-interval-seconds={value}",
    ]) == 2
    assert loaded == []


def test_missing_factory_module_is_bounded_json_error(capsys):
    rc = cli.main([
        "--capture-factory", "missing_home_factory_module_20261008:factory",
        "--session-id", "session", "--user-id", "user",
        "--source-id", "source", "--location", "home",
        "--allow-physical-camera", "--require-event",
    ])
    assert rc == 2
    assert json.loads(capsys.readouterr().out) == {
        "passed": False, "error": "capture factory module could not be imported"
    }


def test_factory_import_error_keeps_exception_chain():
    try:
        cli.load_capture_factory("missing_home_factory_module_20261008:factory")
    except ValueError as exc:
        assert isinstance(exc.__cause__, ImportError)
    else:
        raise AssertionError("expected a bounded ValueError")


@pytest.mark.parametrize("field", ["session_id", "user_id", "source_id", "location"])
@pytest.mark.parametrize("bad_value", [None, 0, False, "  "])
def test_validation_rejects_nonstring_or_blank_identity(field, bad_value):
    config = dict(
        session_id="session", user_id="tenant", source_id="camera", location="kitchen",
        device_index=0, max_frames=3, confirmations=2,
        min_interval_seconds=1.0, min_confidence=0.8,
        require_event=True, allow_physical_camera=True,
    )
    config[field] = bad_value
    with pytest.raises(ValueError, match="session_id, user_id, source_id and location are required"):
        cli.validate_config(**config)


@pytest.mark.parametrize("field,error", [
    ("allow_physical_camera", "physical camera access requires explicit opt-in"),
    ("require_event", "physical hardware acceptance requires --require-event"),
])
@pytest.mark.parametrize("bad_value", [1, 1.0, "true", "True", [True], {"enabled": True}, -1])
def test_validation_rejects_truthy_nonboolean_consent_or_event_flags(field, error, bad_value):
    config = dict(
        session_id="session", user_id="tenant", source_id="camera", location="kitchen",
        device_index=0, max_frames=3, confirmations=2,
        min_interval_seconds=1.0, min_confidence=0.8,
        require_event=True, allow_physical_camera=True,
    )
    config[field] = bad_value
    with pytest.raises(ValueError, match=error):
        cli.validate_config(**config)


@pytest.mark.parametrize("spec", [
    "..:factory", ".:factory", ":factory", "json:", "json",
    "json:factory.name", None, 4, " :factory", "json:  ",
])
def test_capture_factory_rejects_malformed_module_path_as_bounded_value_error(spec):
    with pytest.raises(ValueError, match="capture factory must use module:callable syntax"):
        cli.load_capture_factory(spec)


def test_capture_factory_accepts_callable_and_rejects_noncallable():
    import json as json_module
    assert cli.load_capture_factory("json:loads") is json_module.loads
    with pytest.raises(ValueError, match="capture factory is not callable"):
        cli.load_capture_factory("json:__name__")


def test_cli_malformed_capture_factory_returns_bounded_json_error(capsys):
    rc = cli.main([
        "--capture-factory", "..:factory",
        "--session-id", "session", "--user-id", "user",
        "--source-id", "source", "--location", "home",
        "--allow-physical-camera", "--require-event",
    ])
    assert rc == 2
    assert json.loads(capsys.readouterr().out) == {
        "passed": False, "error": "capture factory must use module:callable syntax"
    }

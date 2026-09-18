"""Regression tests for server-owned Home Agent capture-session lookup."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession


NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _session() -> CaptureSession:
    return CaptureSession(
        session_id="capture-opaque-1",
        user_id="user-a",
        source_id="camera-entry",
        started_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def test_registered_session_resolves_for_bound_user_and_source() -> None:
    registry = CaptureSessionRegistry()
    session = _session()
    registry.register(session)

    resolved = registry.resolve(
        session_id=session.session_id,
        user_id="user-a",
        source_id="camera-entry",
        now=NOW + timedelta(seconds=30),
    )

    assert resolved is session


def test_session_id_cannot_cross_user_or_source_boundary() -> None:
    registry = CaptureSessionRegistry()
    session = _session()
    registry.register(session)

    with pytest.raises(PermissionError, match="capture session"):
        registry.resolve(
            session_id=session.session_id,
            user_id="user-b",
            source_id="camera-entry",
            now=NOW + timedelta(seconds=30),
        )

    with pytest.raises(PermissionError, match="capture session"):
        registry.resolve(
            session_id=session.session_id,
            user_id="user-a",
            source_id="camera-office",
            now=NOW + timedelta(seconds=30),
        )


def test_expired_session_is_rejected_and_evicted() -> None:
    registry = CaptureSessionRegistry()
    session = _session()
    registry.register(session)

    with pytest.raises(PermissionError, match="capture session"):
        registry.resolve(
            session_id=session.session_id,
            user_id="user-a",
            source_id="camera-entry",
            now=session.expires_at,
        )

    with pytest.raises(PermissionError, match="capture session"):
        registry.resolve(
            session_id=session.session_id,
            user_id="user-a",
            source_id="camera-entry",
            now=NOW + timedelta(minutes=1),
        )


def test_revoked_session_cannot_be_reused() -> None:
    registry = CaptureSessionRegistry()
    session = _session()
    registry.register(session)

    assert registry.revoke(session_id=session.session_id) is True
    assert registry.revoke(session_id=session.session_id) is False

    with pytest.raises(PermissionError, match="capture session"):
        registry.resolve(
            session_id=session.session_id,
            user_id="user-a",
            source_id="camera-entry",
            now=NOW + timedelta(seconds=30),
        )


def test_lookup_requires_timezone_aware_server_time() -> None:
    registry = CaptureSessionRegistry()
    session = _session()
    registry.register(session)

    with pytest.raises(ValueError, match="timezone-aware"):
        registry.resolve(
            session_id=session.session_id,
            user_id="user-a",
            source_id="camera-entry",
            now=datetime(2026, 9, 11, 12, 1),
        )


def test_revoke_for_user_fences_only_exact_tenant_sessions() -> None:
    registry = CaptureSessionRegistry()
    tenant_a_one = _session()
    tenant_a_two = CaptureSession(
        session_id="capture-opaque-2",
        user_id="user-a",
        source_id="camera-office",
        started_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    tenant_b = CaptureSession(
        session_id="capture-opaque-3",
        user_id="user-b",
        source_id="camera-entry",
        started_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    for session in (tenant_a_one, tenant_a_two, tenant_b):
        registry.register(session)

    assert registry.revoke_for_user(user_id="user-a") == 2

    for session in (tenant_a_one, tenant_a_two):
        with pytest.raises(PermissionError, match="capture session"):
            registry.resolve(
                session_id=session.session_id,
                user_id=session.user_id,
                source_id=session.source_id,
                now=NOW + timedelta(seconds=30),
            )

    assert registry.resolve(
        session_id=tenant_b.session_id,
        user_id="user-b",
        source_id="camera-entry",
        now=NOW + timedelta(seconds=30),
    ) is tenant_b


def test_revoke_for_user_rejects_blank_owner_without_mutation() -> None:
    registry = CaptureSessionRegistry()
    session = _session()
    registry.register(session)

    with pytest.raises(ValueError, match="user_id is required"):
        registry.revoke_for_user(user_id="   ")

    assert registry.resolve(
        session_id=session.session_id,
        user_id="user-a",
        source_id="camera-entry",
        now=NOW + timedelta(seconds=30),
    ) is session

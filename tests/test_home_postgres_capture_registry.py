"""Real-PostgreSQL cross-worker capture-session contract, no hardware."""
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.postgres_capture_registry import PostgresCaptureSessionRegistry


@pytest.fixture
def capture_db(monkeypatch):
    dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real PostgreSQL DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "home_sessions_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    env_name = "HOME_SESSION_DSN_" + uuid4().hex
    monkeypatch.setenv(env_name, make_conninfo(dsn, options=f"-c search_path={schema}"))
    factory = get_postgres_connection_factory(
        Settings(_env_file=None, postgres_dsn_env=env_name)
    )
    try:
        yield factory
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)
            ))


def _session(user_id="tenant-a", source_id="camera-a", *,
             offset=timedelta(seconds=-2)):
    started = datetime.now(timezone.utc) + offset
    return CaptureSession(
        session_id=uuid4().hex, user_id=user_id, source_id=source_id,
        started_at=started, expires_at=started + timedelta(minutes=5),
    )


def test_cross_worker_resolution_and_tenant_source_binding(capture_db):
    first = PostgresCaptureSessionRegistry(capture_db)
    second = PostgresCaptureSessionRegistry(capture_db)
    session = _session()
    first.register(session)
    assert second.resolve(session_id=session.session_id, user_id="tenant-a",
                          source_id="camera-a") == session
    for user, source in (("tenant-b", "camera-a"), ("tenant-a", "camera-b")):
        with pytest.raises(PermissionError):
            second.resolve(session_id=session.session_id, user_id=user,
                           source_id=source)
    with pytest.raises(ValueError):
        first.register(session)


def test_revocation_visible_across_workers(capture_db):
    first = PostgresCaptureSessionRegistry(capture_db)
    second = PostgresCaptureSessionRegistry(capture_db)
    session = _session()
    first.register(session)
    assert second.revoke(session_id=session.session_id) is True
    assert first.revoke(session_id=session.session_id) is False
    with pytest.raises(PermissionError):
        first.resolve(session_id=session.session_id, user_id="tenant-a",
                      source_id="camera-a")


def test_database_time_rejects_expired_and_future_sessions(capture_db):
    registry = PostgresCaptureSessionRegistry(capture_db)
    for offset in (timedelta(minutes=-10), timedelta(minutes=1)):
        session = _session(offset=offset)
        registry.register(session)
        with pytest.raises(PermissionError):
            registry.resolve(session_id=session.session_id, user_id=session.user_id,
                             source_id=session.source_id,
                             now=datetime(2099, 1, 1, tzinfo=timezone.utc))


def test_revoke_for_one_tenant_does_not_affect_neighbor(capture_db):
    registry = PostgresCaptureSessionRegistry(capture_db)
    owner = _session()
    neighbor = _session(user_id="tenant-b")
    registry.register(owner)
    registry.register(neighbor)
    assert registry.revoke_for_user(user_id="tenant-a") == 1
    assert registry.revoke_for_user(user_id="tenant-a") == 0
    with pytest.raises(PermissionError):
        registry.resolve(session_id=owner.session_id, user_id=owner.user_id,
                         source_id=owner.source_id)
    assert registry.resolve(session_id=neighbor.session_id, user_id=neighbor.user_id,
                            source_id=neighbor.source_id) == neighbor


def test_authorize_image_write_requires_active_session_and_observation_window(capture_db):
    registry = PostgresCaptureSessionRegistry(capture_db)
    session = _session()
    registry.register(session)
    observed = session.started_at + timedelta(seconds=1)
    with capture_db() as conn:
        registry.authorize_image_write(
            conn, session_id=session.session_id, user_id=session.user_id,
            source_id=session.source_id, observed_at=observed,
        )
    for owner, source, stamp in (
        ("tenant-b", session.source_id, observed),
        (session.user_id, "wrong-camera", observed),
        (session.user_id, session.source_id, session.started_at - timedelta(seconds=1)),
        (session.user_id, session.source_id, session.expires_at),
        (session.user_id, session.source_id, datetime(2099, 1, 1, tzinfo=timezone.utc)),
    ):
        with capture_db() as conn:
            with pytest.raises(PermissionError):
                registry.authorize_image_write(
                    conn, session_id=session.session_id, user_id=owner,
                    source_id=source, observed_at=stamp,
                )
    with capture_db() as conn:
        with pytest.raises(ValueError, match="timezone-aware"):
            registry.authorize_image_write(
                conn, session_id=session.session_id, user_id=session.user_id,
                source_id=session.source_id, observed_at=datetime(2026, 10, 28),
            )


def test_authorize_image_write_serializes_with_revocation(capture_db):
    import psycopg

    registry = PostgresCaptureSessionRegistry(capture_db)
    session = _session()
    registry.register(session)
    observed = session.started_at + timedelta(seconds=1)
    with capture_db() as writer:
        registry.authorize_image_write(
            writer, session_id=session.session_id, user_id=session.user_id,
            source_id=session.source_id, observed_at=observed,
        )
        # An independent connection cannot revoke while the image writer holds
        # the same session row. Roll back the timed-out attempt before commit.
        with capture_db() as revoker:
            revoker.execute("SET LOCAL lock_timeout = '150ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                revoker.execute(
                    "UPDATE home_capture_sessions SET revoked_at=clock_timestamp() "
                    "WHERE session_id=%s", (session.session_id,),
                )
            revoker.rollback()
    assert registry.revoke(session_id=session.session_id) is True
    with capture_db() as conn:
        with pytest.raises(PermissionError):
            registry.authorize_image_write(
                conn, session_id=session.session_id, user_id=session.user_id,
                source_id=session.source_id, observed_at=observed,
            )


def test_authorize_image_write_rejects_expired_and_future_sessions(capture_db):
    registry = PostgresCaptureSessionRegistry(capture_db)
    for offset in (timedelta(minutes=-10), timedelta(minutes=1)):
        session = _session(offset=offset)
        registry.register(session)
        with capture_db() as conn:
            with pytest.raises(PermissionError):
                registry.authorize_image_write(
                    conn, session_id=session.session_id, user_id=session.user_id,
                    source_id=session.source_id, observed_at=session.started_at,
                )

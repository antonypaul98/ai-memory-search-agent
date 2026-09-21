from tests.postgres_fence_fakes import is_fence_query, UnfencedCursor
"""Legacy ownership, preview and target transaction acceptance for review state."""
import os
import sqlite3
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.db.postgres_review_schedule_migration import (
    migrate_review_schedules_to_postgres,
    preview_review_schedule_migration,
)
from app.db.postgres_review_schedule_store import PostgresReviewScheduleStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.video_registry import get_video_registry


def _source(tmp_path, owner="owner"):
    path = tmp_path / "review?source.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE video_registry(user_id TEXT, video_id TEXT);
            CREATE TABLE memory_review_schedule(
                user_id TEXT, video_id TEXT, last_reviewed_at TEXT, next_review_at TEXT,
                review_count INTEGER, last_result TEXT, updated_at TEXT
            );
        """)
        for tenant in (owner, owner + "-other"):
            for video in ("a", "b"):
                conn.execute("INSERT INTO video_registry VALUES (?, ?)", (tenant, video))
                conn.execute(
                    "INSERT INTO memory_review_schedule VALUES (?, ?, ?, ?, 2, 'good', ?)",
                    (tenant, video, "2026-09-01T00:00:00+00:00", "2026-09-08T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
                )
    return Settings(_env_file=None, sqlite_path=str(path), postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN")


def test_review_preview_is_read_only_tenant_scoped_and_needs_no_dsn(tmp_path, monkeypatch):
    settings = _source(tmp_path)
    monkeypatch.delenv(settings.postgres_dsn_env, raising=False)
    original = (tmp_path / "review?source.db").read_bytes()
    assert preview_review_schedule_migration(settings, user_id="owner").to_dict() == {"schedules": 2, "tenants": 1}
    assert (tmp_path / "review?source.db").read_bytes() == original
    with pytest.raises(ValueError, match="user_id must not be blank or padded"):
        preview_review_schedule_migration(settings, user_id=" owner ")


@pytest.mark.parametrize("mutation", [
    "DELETE FROM video_registry WHERE user_id = 'owner' AND video_id = 'a'",
    "UPDATE memory_review_schedule SET video_id = '' WHERE user_id = 'owner'",
    "UPDATE memory_review_schedule SET review_count = 0 WHERE user_id = 'owner'",
    "UPDATE memory_review_schedule SET last_result = 'unknown' WHERE user_id = 'owner'",
    "UPDATE memory_review_schedule SET next_review_at = 'invalid' WHERE user_id = 'owner'",
    "UPDATE memory_review_schedule SET last_reviewed_at = '2026-09-01' WHERE user_id = 'owner'",
    "INSERT INTO memory_review_schedule SELECT * FROM memory_review_schedule WHERE user_id = 'owner'",
])
def test_review_apply_revalidates_and_rejects_invalid_source_before_target(tmp_path, mutation):
    settings = _source(tmp_path)
    assert preview_review_schedule_migration(settings, user_id="owner").schedules == 2
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute(mutation)
    target = MagicMock()
    with pytest.raises(ValueError):
        migrate_review_schedules_to_postgres(settings, user_id="owner", connection_factory=target)
    target.assert_not_called()


def test_review_cli_reports_counts_and_sanitizes_failures(tmp_path, monkeypatch, capsys):
    from scripts import migrate_review_schedules_to_postgres as cli
    settings = _source(tmp_path)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["migrate", "--user-id", "owner"])
    assert cli.main() == 0
    assert capsys.readouterr().out.strip() == '{"mode": "preview", "schedules": 2, "tenants": 1}'
    monkeypatch.setattr("sys.argv", ["migrate", "--user-id", "owner", "--apply"])
    monkeypatch.setattr(cli, "migrate_review_schedules_to_postgres", MagicMock(side_effect=RuntimeError("sensitive driver details")))
    assert cli.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sensitive" not in captured.err
    assert "migration failed" in captured.err


@pytest.mark.skipif(not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"), reason="real Postgres DSN required")
def test_real_postgres_review_migration_rollback_retry_and_target_preservation(tmp_path):
    import psycopg

    owner = "review-migration-" + uuid4().hex
    other = owner + "-other"
    settings = _source(tmp_path, owner)
    settings.memory_store_backend = "postgres"
    factory = get_postgres_connection_factory(settings)
    registry = get_video_registry(settings)
    store = PostgresReviewScheduleStore(factory)
    try:
        for tenant in (owner, other):
            for video in ("a", "b"):
                registry.upsert_video(user_id=tenant, video_id=video, url="https://example.test/review", title="fixture", channel="")
        # Other tenant state must remain untouched even for the same video IDs.
        store.record_result(user_id=other, video_id="a", outcome="easy", reviewed_iso="2026-09-10T00:00:00+00:00", next_iso="2026-09-24T00:00:00+00:00")
        other_before = store.get(user_id=other, video_id="a")

        class FailOnSecondInsert:
            def __enter__(self):
                self.conn = factory()
                self.conn.__enter__()
                return self
            def __exit__(self, *args):
                return self.conn.__exit__(*args)
            def execute(self, sql, params=None):
                if is_fence_query(sql):
                    return UnfencedCursor()
                if sql.startswith("INSERT INTO memory_review_schedule") and params[1] == "b":
                    self.conn.execute("SELECT 1 / 0")
                return self.conn.execute(sql, params)

        with pytest.raises(psycopg.errors.DivisionByZero):
            migrate_review_schedules_to_postgres(settings, user_id=owner, connection_factory=FailOnSecondInsert)
        assert store.get(user_id=owner, video_id="a") is None
        assert store.get(user_id=owner, video_id="b") is None

        # Missing target ownership also rolls back earlier rows in the batch.
        with factory() as conn:
            conn.execute("DELETE FROM video_registry WHERE user_id = %s AND video_id = 'b'", (owner,))
        with pytest.raises(ValueError, match="target lacks exact tenant"):
            migrate_review_schedules_to_postgres(settings, user_id=owner, connection_factory=factory)
        assert store.get(user_id=owner, video_id="a") is None
        registry.upsert_video(user_id=owner, video_id="b", url="https://example.test/review", title="fixture", channel="")

        store.record_result(user_id=owner, video_id="a", outcome="hard", reviewed_iso="2026-09-12T00:00:00+00:00", next_iso="2026-09-15T00:00:00+00:00")
        before = store.get(user_id=owner, video_id="a")
        first = migrate_review_schedules_to_postgres(settings, user_id=owner, connection_factory=factory)
        second = migrate_review_schedules_to_postgres(settings, user_id=owner, connection_factory=factory)
        assert first.to_dict() == {"schedules_seen": 2, "schedules_inserted": 1, "schedules_skipped_existing": 1}
        assert second.to_dict() == {"schedules_seen": 2, "schedules_inserted": 0, "schedules_skipped_existing": 2}
        assert store.get(user_id=owner, video_id="a") == before
        assert store.get(user_id=owner, video_id="b")["review_count"] == 2
        assert store.get(user_id=other, video_id="a") == other_before
        assert store.get(user_id=other, video_id="b") is None
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM memory_review_schedule WHERE user_id IN (%s, %s)", (owner, other))
            conn.execute("DELETE FROM video_registry WHERE user_id IN (%s, %s)", (owner, other))

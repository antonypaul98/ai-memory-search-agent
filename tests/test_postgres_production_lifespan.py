"""Real app/worker lifecycle and populated relational operations in one profile.

An isolated Postgres schema prevents live worker threads from claiming jobs left
by unrelated tests. Chroma retains its separate vector-storage boundary; no
relational service, worker loop or store is replaced with a fake implementation.
"""
import asyncio
import os
import sqlite3
from threading import Event
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.auth_store_factory import get_auth_store
from app.db.postgres_job_store import PostgresJobStore
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.video import SourceType
from app.services.event_bus import EventBus
from app.services.privacy_service import PrivacyService
import app.main as main_module
import app.services.job_worker as worker_module


@pytest.mark.parametrize("fail_in_lifespan", [False, True])
def test_complete_postgres_lifespan_and_populated_tenant_operations(monkeypatch, tmp_path, fail_in_lifespan):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "p03_lifespan_" + uuid4().hex
    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    # Selected-store caches are keyed by the environment alias. Give each
    # isolated database schema its own alias so parametrized cases cannot reuse
    # a connection factory captured for a schema already dropped by cleanup.
    dsn_alias = "P03_LIFESPAN_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    monkeypatch.setenv("P03_LIFESPAN_AUTH_SECRET", uuid4().hex)
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env=dsn_alias, auth_secret_env="P03_LIFESPAN_AUTH_SECRET",
        sqlite_path=str(tmp_path / "forbidden.db"), chroma_persist_dir=str(tmp_path / "chroma"),
        jobs_enabled=True, worker_mode="all", job_worker_concurrency=2,
        job_poll_interval_sec=0.05, auth_enabled=True, local_demo_mode=False,
    )
    attempts = []
    polled = Event()
    claim = PostgresJobStore.claim_next_item

    def observed_claim(self, **kwargs):
        result = claim(self, **kwargs)
        polled.set()
        return result

    def reject_sqlite(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("production relational runtime opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(PostgresJobStore, "claim_next_item", observed_claim)
    started_workers = []

    async def run():
        async with main_module.lifespan(main_module.app):
            worker = worker_module._WORKER
            started_workers.append(worker)
            assert worker is not None
            assert polled.wait(timeout=10), "real worker did not complete a Postgres claim query"
            assert len(worker._threads) == 2
            assert all(thread.is_alive() for thread in worker._threads)

            auth = get_auth_store(settings)
            owner = auth.create_user(email="owner@example.test", password=uuid4().hex, display_name="Owner")
            other = auth.create_user(email="other@example.test", password=uuid4().hex, display_name="Other")
            token = auth.create_session(owner.user_id)
            assert auth.resolve_token(token).user_id == owner.user_id

            privacy = PrivacyService(settings)
            memories = {}
            for user in (owner, other):
                memories[user.user_id] = privacy._memory_store.upsert(
                    user_id=user.user_id, source_type=SourceType.WEB, external_id="shared",
                    canonical_url="https://example.test/shared", title="Production evidence",
                )
                privacy._registry.upsert_video(
                    user_id=user.user_id, video_id="shared", url="https://example.test/shared",
                    title="Production evidence", channel="fixture",
                )
                privacy._fts.upsert(
                    user_id=user.user_id, video_id="shared", level="capsule", doc_id="shared",
                    title="Production evidence", body="tenant scoped production evidence",
                )
                privacy._review_schedule.record_result(user_id=user.user_id, video_id="shared", result="good")
            assert privacy._fts.search("production", user_id=owner.user_id)
            assert privacy._fts.search("production", user_id="unrelated") == []
            exported = privacy.export_user_data(user_id=owner.user_id)
            assert [memory["memory_id"] for memory in exported["memories"]] == [memories[owner.user_id].memory_id]
            assert exported["review_schedules"][0]["user_id"] == owner.user_id

            events = EventBus(settings)
            events.emit(user_id=owner.user_id, event_type="acceptance.state_changed", payload={"count": 1})
            assert events.list_events(user_id=owner.user_id)[0]
            assert events.list_events(user_id=other.user_id)[0] == []
            with pytest.raises(KeyError):
                privacy.delete_memory(memory_id=memories[owner.user_id].memory_id, user_id=other.user_id)
            privacy.delete_memory(memory_id=memories[owner.user_id].memory_id, user_id=owner.user_id)
            assert privacy._fts.search("production", user_id=owner.user_id) == []
            assert privacy._fts.search("production", user_id=other.user_id)
            assert privacy._memory_store.get(memories[other.user_id].memory_id, user_id=other.user_id)
            assert privacy.export_user_data(user_id=owner.user_id)["review_schedules"] == []
            auth.revoke_session(token)
            assert auth.resolve_token(token) is None
            if fail_in_lifespan:
                raise RuntimeError("injected lifespan failure")

    try:
        if fail_in_lifespan:
            with pytest.raises(RuntimeError, match="injected lifespan failure"):
                asyncio.run(run())
        else:
            asyncio.run(run())
        assert worker_module._WORKER is None
        assert all(worker._stop.is_set() for worker in started_workers)
        assert all(not thread.is_alive() for worker in started_workers for thread in worker._threads)
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()
    finally:
        worker_module.stop_job_worker()
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

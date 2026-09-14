"""Combined real-Postgres privacy acceptance under the live production profile.

This intentionally exercises the existing production lifespan and selected stores
rather than replacing them with test doubles. Chroma remains the separate vector
boundary; Python relational SQLite is rejected for every executed path.
"""
from __future__ import annotations

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
from app.models.feedback import FeedbackIssue, FeedbackSubmitRequest
from app.models.video import SourceType
from app.services.event_bus import EventBus
from app.services.feedback_service import FeedbackService
from app.services.privacy_erasure import delete_production_user_data
from app.services.privacy_service import PrivacyService
import app.main as main_module
import app.services.job_worker as worker_module


def test_complete_postgres_profile_combines_export_and_tenant_erasure(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "p03_combined_privacy_" + uuid4().hex
    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "P03_COMBINED_PRIVACY_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    monkeypatch.setenv("P03_COMBINED_PRIVACY_AUTH_SECRET", uuid4().hex)
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env=dsn_alias,
        auth_secret_env="P03_COMBINED_PRIVACY_AUTH_SECRET",
        sqlite_path=str(tmp_path / "forbidden.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        jobs_enabled=True,
        worker_mode="all",
        job_worker_concurrency=2,
        job_poll_interval_sec=0.05,
        auth_enabled=True,
        local_demo_mode=False,
    )

    sqlite_attempts: list[bool] = []
    polled = Event()
    original_claim = PostgresJobStore.claim_next_item

    def observed_claim(self, **kwargs):
        result = original_claim(self, **kwargs)
        polled.set()
        return result

    def reject_sqlite(*args, **kwargs):
        sqlite_attempts.append(True)
        raise AssertionError("combined production privacy acceptance opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(PostgresJobStore, "claim_next_item", observed_claim)

    async def run() -> None:
        async with main_module.lifespan(main_module.app):
            worker = worker_module._WORKER
            assert worker is not None
            assert polled.wait(timeout=10), "live workers never completed a Postgres claim query"
            assert len(worker._threads) == 2
            assert all(thread.is_alive() for thread in worker._threads)

            auth = get_auth_store(settings)
            owner = auth.create_user(
                email=f"owner-{uuid4().hex}@example.test",
                password=uuid4().hex,
                display_name="Owner",
            )
            other = auth.create_user(
                email=f"other-{uuid4().hex}@example.test",
                password=uuid4().hex,
                display_name="Other",
            )

            privacy = PrivacyService(settings)
            memories = {}
            for user in (owner, other):
                memories[user.user_id] = privacy._memory_store.upsert(
                    user_id=user.user_id,
                    source_type=SourceType.WEB,
                    external_id="shared-privacy-source",
                    canonical_url="https://example.test/shared-privacy-source",
                    title="Combined privacy acceptance",
                )
                privacy._registry.upsert_video(
                    user_id=user.user_id,
                    video_id="shared-privacy-source",
                    url="https://example.test/shared-privacy-source",
                    title="Combined privacy acceptance",
                    channel="fixture",
                )
                privacy._fts.upsert(
                    user_id=user.user_id,
                    video_id="shared-privacy-source",
                    level="capsule",
                    doc_id="shared-privacy-source",
                    title="Combined privacy acceptance",
                    body="tenant scoped combined privacy evidence",
                )
                privacy._review_schedule.record_result(
                    user_id=user.user_id,
                    video_id="shared-privacy-source",
                    result="good",
                )

            feedback = FeedbackService(settings)
            for user, suffix in ((owner, "owner"), (other, "other")):
                interaction_id = f"combined-privacy-{suffix}-{uuid4().hex}"
                feedback.record_interaction(
                    interaction_id=interaction_id,
                    user_id=user.user_id,
                    task_type="general",
                    route_id="provider:model",
                    output_budget_tokens=320,
                    completion_tokens=200,
                    route_fingerprint=f"combined-{suffix}",
                )
                submitted = feedback.submit(
                    user_id=user.user_id,
                    request=FeedbackSubmitRequest(
                        interaction_id=interaction_id,
                        rating=4,
                        issues=[FeedbackIssue.TOO_LONG],
                        comment=f"{suffix} private combined acceptance feedback",
                    ),
                )
                assert submitted.duplicate is False
                assert submitted.reward_credits > 0
                assert submitted.preference_updated is True

            events = EventBus(settings)
            events.emit(
                user_id=owner.user_id,
                event_type="acceptance.combined_privacy",
                payload={"count": 1},
            )
            owner_events, owner_cursor = events.list_events(user_id=owner.user_id)
            other_events, other_cursor = events.list_events(user_id=other.user_id)
            assert owner_events
            assert owner_cursor is None
            assert other_events == []
            assert other_cursor is None

            owner_export = privacy.export_user_data(user_id=owner.user_id)
            other_export = privacy.export_user_data(user_id=other.user_id)
            assert [row["memory_id"] for row in owner_export["memories"]] == [
                memories[owner.user_id].memory_id
            ]
            assert [row["memory_id"] for row in other_export["memories"]] == [
                memories[other.user_id].memory_id
            ]
            for collection in (
                "interactions",
                "feedback",
                "credit_ledger",
                "output_preferences",
            ):
                owner_rows = owner_export["feedback_records"][collection]
                other_rows = other_export["feedback_records"][collection]
                assert owner_rows and other_rows
                assert all(row["user_id"] == owner.user_id for row in owner_rows)
                assert all(row["user_id"] == other.user_id for row in other_rows)

            result = delete_production_user_data(
                settings,
                user_id=owner.user_id,
                privacy_service=privacy,
            )
            assert result["deleted"] is True
            assert result["memory_deleted_count"] == 1
            assert not result["memory_errors"]
            assert all(count > 0 for count in result["feedback_deleted"].values())

            assert privacy._fts.search("combined", user_id=owner.user_id) == []
            assert privacy._fts.search("combined", user_id=other.user_id)
            assert privacy._memory_store.get(
                memories[other.user_id].memory_id,
                user_id=other.user_id,
            )

            erased_export = privacy.export_user_data(user_id=owner.user_id)
            assert erased_export["memories"] == []
            assert erased_export["review_schedules"] == []
            for rows in erased_export["feedback_records"].values():
                assert rows == []

            preserved_export = privacy.export_user_data(user_id=other.user_id)
            assert preserved_export["memories"]
            assert preserved_export["review_schedules"]
            assert all(preserved_export["feedback_records"][key] for key in (
                "interactions",
                "feedback",
                "credit_ledger",
                "output_preferences",
            ))

    try:
        asyncio.run(run())
        assert worker_module._WORKER is None
        assert sqlite_attempts == []
        assert not (tmp_path / "forbidden.db").exists()
    finally:
        worker_module.stop_job_worker()
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

"""Tests for universal memory store and schema."""

import sqlite3

import pytest

from app.db.memory_store import MemoryStore
from app.db.schema import SCHEMA_VERSION, migrate
from app.models.lifecycle import MemoryLifecycleState
from app.models.trust import TrustMetrics, TrustTier, VerificationStatus
from app.models.universal_memory import MemoryProvenance
from app.models.video import SourceType
from app.services.trust_engine import TrustEngine


@pytest.fixture
def memory_store(test_settings) -> MemoryStore:
    return MemoryStore(test_settings)


class TestMemoryStore:
    def test_upsert_and_get_by_external(self, memory_store: MemoryStore) -> None:
        memory = memory_store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="vid123",
            canonical_url="https://www.youtube.com/watch?v=vid123",
            title="Demo Video",
            source_author="Channel",
            provenance=MemoryProvenance(ingest_url="https://youtu.be/vid123"),
            lifecycle_state=MemoryLifecycleState.CAPTURED,
        )
        assert memory.memory_id
        assert memory.lifecycle_state == MemoryLifecycleState.CAPTURED

        fetched = memory_store.get_by_external(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="vid123",
        )
        assert fetched is not None
        assert fetched.title == "Demo Video"

    def test_content_version_increments(self, memory_store: MemoryStore) -> None:
        memory_store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="v1",
            canonical_url="https://youtu.be/v1",
            title="First",
        )
        second = memory_store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="v1",
            canonical_url="https://youtu.be/v1",
            title="Second",
            increment_content_version=True,
            version_reason="reindex",
        )
        assert second.content_version == 2
        versions = memory_store.list_versions(second.memory_id)
        assert len(versions) >= 1

    def test_lifecycle_transition_audit(self, memory_store: MemoryStore) -> None:
        memory = memory_store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="life1",
            canonical_url="https://youtu.be/life1",
            title="Life",
            lifecycle_state=MemoryLifecycleState.CAPTURED,
        )
        memory_store.update_lifecycle_state(
            memory_id=memory.memory_id,
            user_id="user-a",
            to_state=MemoryLifecycleState.PARSED,
            reason="parsed",
        )
        transitions = memory_store.list_transitions(memory.memory_id)
        assert len(transitions) == 2
        assert transitions[0].to_state == MemoryLifecycleState.CAPTURED
        assert transitions[1].to_state == MemoryLifecycleState.PARSED

    def test_trust_history_persisted(self, memory_store: MemoryStore) -> None:
        memory = memory_store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="trust1",
            canonical_url="https://youtu.be/trust1",
            title="Trust",
        )
        trust = TrustMetrics(
            source_reliability=0.8,
            freshness=0.9,
            verification=0.7,
            evidence_strength=0.6,
            confidence=0.75,
            overall=0.75,
            tier=TrustTier.TRUSTED,
            computed_at="2026-01-01T00:00:00+00:00",
        )
        memory_store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="trust1",
            canonical_url="https://youtu.be/trust1",
            title="Trust",
            trust=trust,
        )
        history = memory_store.list_trust_history(memory.memory_id)
        assert len(history) == 1
        assert history[0].overall == 0.75


class TestTrustEngine:
    def test_compute_scores(self, memory_store: MemoryStore) -> None:
        memory = memory_store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="score1",
            canonical_url="https://youtu.be/score1",
            title="Score",
            verification_status=VerificationStatus.VERIFIED,
        )
        engine = TrustEngine(store=memory_store)
        metrics = engine.compute(memory=memory, chunk_count=5, has_capsule=True)
        assert 0.0 <= metrics.overall <= 1.0
        assert metrics.evidence_strength > 0.5
        assert metrics.tier in {TrustTier.TRUSTED, TrustTier.MODERATE}


class TestSchemaV4:
    def test_migration_creates_brain_tables(self, test_settings) -> None:
        migrate(test_settings)
        conn = sqlite3.connect(test_settings.sqlite_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == SCHEMA_VERSION
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "memory_records" in tables
            assert "memory_lifecycle_events" in tables
            assert "memory_trust_history" in tables
            assert "kg_entities" in tables
            assert "kg_relations" in tables
            assert "kg_memory_entities" in tables
        finally:
            conn.close()

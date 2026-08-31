"""Postgres persistence for canonical universal memory records.

This is the P-03 production-store counterpart to ``MemoryStore``.  It preserves
canonical identity, tenant scoping, provenance, lifecycle history, versions and
trust snapshots while keeping credentials environment-owned through the shared
Postgres runtime.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.db.postgres_job_repository import ConnectionFactory
from app.models.lifecycle import LifecycleTransition, MemoryLifecycleState
from app.models.trust import TrustMetrics, VerificationStatus
from app.models.universal_memory import (
    MemoryEmbeddingRefs,
    MemoryProvenance,
    MemoryVersionSnapshot,
    UniversalMemory,
    UniversalMemoryDetail,
)
from app.models.video import SourceType


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def ensure_postgres_memory_schema(connection_factory: ConnectionFactory) -> None:
    """Create the canonical-memory relational surface idempotently."""
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_records (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                external_id TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                title TEXT NOT NULL,
                source_author TEXT NOT NULL DEFAULT '',
                lifecycle_state TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                object_schema_version INTEGER NOT NULL DEFAULT 1,
                content_version INTEGER NOT NULL DEFAULT 1,
                provenance_json TEXT NOT NULL DEFAULT '{}',
                embedding_refs_json TEXT NOT NULL DEFAULT '{}',
                trust_snapshot_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                relationship_summary_json TEXT NOT NULL DEFAULT '{}',
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, source_type, external_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_records_user_updated
            ON memory_records(user_id, updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_lifecycle_events (
                id BIGSERIAL PRIMARY KEY,
                memory_id TEXT NOT NULL REFERENCES memory_records(memory_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL DEFAULT 'system',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_lifecycle_memory
            ON memory_lifecycle_events(memory_id, id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_versions (
                id BIGSERIAL PRIMARY KEY,
                memory_id TEXT NOT NULL REFERENCES memory_records(memory_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                lifecycle_state TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                trust_overall DOUBLE PRECISION,
                title TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(memory_id, version_number)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_trust_history (
                id BIGSERIAL PRIMARY KEY,
                memory_id TEXT NOT NULL REFERENCES memory_records(memory_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                trust_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_trust_memory
            ON memory_trust_history(memory_id, id DESC)
            """
        )


class PostgresMemoryStore:
    """Postgres CRUD with parity to the SQLite canonical ``MemoryStore``."""

    def __init__(self, settings: Settings, connection_factory: ConnectionFactory) -> None:
        self._settings = settings
        self._connect = connection_factory

    def get_by_external(self, *, user_id: str, source_type: SourceType | str, external_id: str) -> UniversalMemory | None:
        st = source_type.value if isinstance(source_type, SourceType) else source_type
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_records WHERE user_id = %s AND source_type = %s AND external_id = %s",
                (user_id, st, external_id),
            ).fetchone()
        return _row_to_memory(row) if row else None

    def get(self, memory_id: str, *, user_id: str | None = None) -> UniversalMemory | None:
        with self._connect() as conn:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM memory_records WHERE memory_id = %s AND user_id = %s",
                    (memory_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM memory_records WHERE memory_id = %s",
                    (memory_id,),
                ).fetchone()
        return _row_to_memory(row) if row else None

    def list_recent(self, *, user_id: str, limit: int = 50) -> list[UniversalMemory]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_records WHERE user_id = %s ORDER BY updated_at DESC LIMIT %s",
                (user_id, limit),
            ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def get_detail(self, memory_id: str, *, user_id: str) -> UniversalMemoryDetail | None:
        memory = self.get(memory_id, user_id=user_id)
        if not memory:
            return None
        return UniversalMemoryDetail(
            **memory.model_dump(),
            transitions=self.list_transitions(memory_id, limit=50),
            versions=self.list_versions(memory_id, limit=20),
        )

    def upsert(
        self,
        *,
        user_id: str,
        source_type: SourceType,
        external_id: str,
        canonical_url: str,
        title: str,
        source_author: str = "",
        provenance: MemoryProvenance | None = None,
        metadata: dict | None = None,
        published_at: str | None = None,
        lifecycle_state: MemoryLifecycleState | None = None,
        verification_status: VerificationStatus | None = None,
        embedding_refs: MemoryEmbeddingRefs | None = None,
        trust: TrustMetrics | None = None,
        relationship_summary: dict | None = None,
        increment_content_version: bool = False,
        version_reason: str = "",
    ) -> UniversalMemory:
        existing = self.get_by_external(user_id=user_id, source_type=source_type, external_id=external_id)
        now = _utc_now()
        memory_id = existing.memory_id if existing else str(uuid.uuid4())
        content_version = existing.content_version if existing else 1
        if increment_content_version and existing:
            content_version += 1

        state = lifecycle_state or (existing.lifecycle_state if existing else MemoryLifecycleState.CAPTURED)
        verification = verification_status or (existing.verification_status if existing else VerificationStatus.UNVERIFIED)
        prov = provenance if provenance is not None else (existing.provenance if existing else MemoryProvenance())
        meta = metadata if metadata is not None else (existing.metadata if existing else {})
        emb = embedding_refs if embedding_refs is not None else (existing.embedding_refs if existing else MemoryEmbeddingRefs())
        rel = relationship_summary if relationship_summary is not None else (existing.relationship_summary if existing else {})
        trust_snapshot = trust if trust is not None else (existing.trust if existing else None)
        created_at = existing.created_at if existing else now
        is_new = existing is None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_records (
                    memory_id, user_id, source_type, external_id, canonical_url, title,
                    source_author, lifecycle_state, verification_status, object_schema_version,
                    content_version, provenance_json, embedding_refs_json, trust_snapshot_json,
                    metadata_json, relationship_summary_json, published_at, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(memory_id) DO UPDATE SET
                    canonical_url=excluded.canonical_url,
                    title=excluded.title,
                    source_author=excluded.source_author,
                    lifecycle_state=excluded.lifecycle_state,
                    verification_status=excluded.verification_status,
                    content_version=excluded.content_version,
                    provenance_json=excluded.provenance_json,
                    embedding_refs_json=excluded.embedding_refs_json,
                    trust_snapshot_json=excluded.trust_snapshot_json,
                    metadata_json=excluded.metadata_json,
                    relationship_summary_json=excluded.relationship_summary_json,
                    published_at=excluded.published_at,
                    updated_at=excluded.updated_at
                """,
                (
                    memory_id, user_id, source_type.value, external_id, canonical_url, title,
                    source_author, state.value, verification.value, 1, content_version,
                    prov.model_dump_json(), emb.model_dump_json(),
                    trust_snapshot.model_dump_json() if trust_snapshot else "{}",
                    json.dumps(meta), json.dumps(rel), published_at, created_at, now,
                ),
            )
            if is_new:
                conn.execute(
                    """
                    INSERT INTO memory_lifecycle_events
                    (memory_id, user_id, from_state, to_state, reason, actor, metadata_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (memory_id, user_id, None, state.value, "created", "system", "{}", now),
                )

        memory = self.get(memory_id, user_id=user_id)
        assert memory is not None
        if increment_content_version:
            self.add_version(memory=memory, reason=version_reason or "content_updated")
        if trust_snapshot:
            self.append_trust_history(memory_id=memory_id, user_id=user_id, trust=trust_snapshot)
        return memory

    def update_lifecycle_state(
        self,
        *,
        memory_id: str,
        user_id: str,
        to_state: MemoryLifecycleState,
        from_state: MemoryLifecycleState | None = None,
        reason: str = "",
        actor: str = "system",
        metadata: dict | None = None,
    ) -> UniversalMemory:
        memory = self.get(memory_id, user_id=user_id)
        if not memory:
            raise KeyError(f"Memory not found: {memory_id}")
        current = from_state or memory.lifecycle_state
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_records SET lifecycle_state = %s, updated_at = %s WHERE memory_id = %s AND user_id = %s",
                (to_state.value, now, memory_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO memory_lifecycle_events
                (memory_id, user_id, from_state, to_state, reason, actor, metadata_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (memory_id, user_id, current.value if current else None, to_state.value, reason, actor, json.dumps(metadata or {}), now),
            )
        updated = self.get(memory_id, user_id=user_id)
        assert updated is not None
        return updated

    def list_transitions(self, memory_id: str, *, limit: int = 50) -> list[LifecycleTransition]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_lifecycle_events WHERE memory_id = %s ORDER BY id ASC LIMIT %s",
                (memory_id, limit),
            ).fetchall()
        return [_row_to_transition(row) for row in rows]

    def add_version(self, *, memory: UniversalMemory, reason: str = "") -> MemoryVersionSnapshot:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) AS max_v FROM memory_versions WHERE memory_id = %s",
                (memory.memory_id,),
            ).fetchone()
            version_number = int(row["max_v"]) + 1
            now = _utc_now()
            snapshot = MemoryVersionSnapshot(
                version_number=version_number,
                lifecycle_state=memory.lifecycle_state,
                verification_status=memory.verification_status,
                trust_overall=memory.trust.overall if memory.trust else None,
                title=memory.title,
                reason=reason,
                created_at=now,
                snapshot={
                    "canonical_url": memory.canonical_url,
                    "content_version": memory.content_version,
                    "embedding_refs": memory.embedding_refs.model_dump(),
                    "metadata": memory.metadata,
                },
            )
            conn.execute(
                """
                INSERT INTO memory_versions
                (memory_id, user_id, version_number, lifecycle_state, verification_status,
                 trust_overall, title, reason, snapshot_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (memory.memory_id, memory.user_id, version_number, memory.lifecycle_state.value,
                 memory.verification_status.value, snapshot.trust_overall, memory.title,
                 reason, json.dumps(snapshot.snapshot), now),
            )
        return snapshot

    def list_versions(self, memory_id: str, *, limit: int = 20) -> list[MemoryVersionSnapshot]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_versions WHERE memory_id = %s ORDER BY version_number DESC LIMIT %s",
                (memory_id, limit),
            ).fetchall()
        return [
            MemoryVersionSnapshot(
                version_number=row["version_number"],
                lifecycle_state=MemoryLifecycleState(row["lifecycle_state"]),
                verification_status=VerificationStatus(row["verification_status"]),
                trust_overall=row["trust_overall"],
                title=row["title"], reason=row["reason"], created_at=_as_text(row["created_at"]) or "",
                snapshot=json.loads(row["snapshot_json"] or "{}"),
            )
            for row in rows
        ]

    def append_trust_history(self, *, memory_id: str, user_id: str, trust: TrustMetrics) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memory_trust_history (memory_id, user_id, trust_json, created_at) VALUES (%s, %s, %s, %s)",
                (memory_id, user_id, trust.model_dump_json(), _utc_now()),
            )

    def list_trust_history(self, memory_id: str, *, limit: int = 20) -> list[TrustMetrics]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT trust_json FROM memory_trust_history WHERE memory_id = %s ORDER BY id DESC LIMIT %s",
                (memory_id, limit),
            ).fetchall()
        return [TrustMetrics.model_validate_json(row["trust_json"]) for row in rows]


def _row_to_memory(row: dict[str, Any]) -> UniversalMemory:
    trust_raw = row["trust_snapshot_json"] or "{}"
    trust = TrustMetrics.model_validate_json(trust_raw) if trust_raw.strip() not in ("", "{}") else None
    return UniversalMemory(
        memory_id=row["memory_id"], user_id=row["user_id"], source_type=SourceType(row["source_type"]),
        external_id=row["external_id"], canonical_url=row["canonical_url"], title=row["title"],
        source_author=row["source_author"], lifecycle_state=MemoryLifecycleState(row["lifecycle_state"]),
        verification_status=VerificationStatus(row["verification_status"]), object_schema_version=row["object_schema_version"],
        content_version=row["content_version"], provenance=MemoryProvenance.model_validate_json(row["provenance_json"] or "{}"),
        embedding_refs=MemoryEmbeddingRefs.model_validate_json(row["embedding_refs_json"] or "{}"), trust=trust,
        metadata=json.loads(row["metadata_json"] or "{}"), relationship_summary=json.loads(row["relationship_summary_json"] or "{}"),
        published_at=_as_text(row["published_at"]), created_at=_as_text(row["created_at"]) or "", updated_at=_as_text(row["updated_at"]) or "",
    )


def _row_to_transition(row: dict[str, Any]) -> LifecycleTransition:
    from_state = row["from_state"]
    return LifecycleTransition(
        memory_id=row["memory_id"],
        from_state=MemoryLifecycleState(from_state) if from_state else None,
        to_state=MemoryLifecycleState(row["to_state"]), reason=row["reason"] or "", actor=row["actor"] or "system",
        metadata=json.loads(row["metadata_json"] or "{}"), created_at=_as_text(row["created_at"]) or "",
    )

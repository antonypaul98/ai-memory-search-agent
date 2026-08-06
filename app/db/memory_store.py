"""SQLite persistence for universal memory records."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate
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


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


class MemoryStore:
    """CRUD for universal memory objects and lifecycle audit."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    def get_by_external(
        self,
        *,
        user_id: str,
        source_type: SourceType | str,
        external_id: str,
    ) -> UniversalMemory | None:
        st = source_type.value if isinstance(source_type, SourceType) else source_type
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM memory_records
                WHERE user_id = ? AND source_type = ? AND external_id = ?
                """,
                (user_id, st, external_id),
            ).fetchone()
        return _row_to_memory(row) if row else None

    def get(self, memory_id: str, *, user_id: str | None = None) -> UniversalMemory | None:
        with get_connection(self._settings) as conn:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM memory_records WHERE memory_id = ? AND user_id = ?",
                    (memory_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM memory_records WHERE memory_id = ?",
                    (memory_id,),
                ).fetchone()
        return _row_to_memory(row) if row else None

    def list_recent(self, *, user_id: str, limit: int = 50) -> list[UniversalMemory]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_records
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_memory(r) for r in rows]

    def get_detail(self, memory_id: str, *, user_id: str) -> UniversalMemoryDetail | None:
        memory = self.get(memory_id, user_id=user_id)
        if not memory:
            return None
        transitions = self.list_transitions(memory_id, limit=50)
        versions = self.list_versions(memory_id, limit=20)
        return UniversalMemoryDetail(**memory.model_dump(), transitions=transitions, versions=versions)

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
        existing = self.get_by_external(
            user_id=user_id, source_type=source_type, external_id=external_id
        )
        now = _utc_now()
        memory_id = existing.memory_id if existing else str(uuid.uuid4())
        content_version = existing.content_version if existing else 1
        if increment_content_version and existing:
            content_version += 1

        state = lifecycle_state or (existing.lifecycle_state if existing else MemoryLifecycleState.CAPTURED)
        verification = verification_status or (
            existing.verification_status if existing else VerificationStatus.UNVERIFIED
        )
        prov = provenance if provenance is not None else (existing.provenance if existing else MemoryProvenance())
        meta = metadata if metadata is not None else (existing.metadata if existing else {})
        emb = embedding_refs if embedding_refs is not None else (
            existing.embedding_refs if existing else MemoryEmbeddingRefs()
        )
        rel = relationship_summary if relationship_summary is not None else (
            existing.relationship_summary if existing else {}
        )
        if trust is not None:
            trust_snapshot = trust
        elif existing is not None:
            trust_snapshot = existing.trust
        else:
            trust_snapshot = None

        created_at = existing.created_at if existing else now
        is_new = existing is None
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO memory_records (
                    memory_id, user_id, source_type, external_id, canonical_url, title,
                    source_author, lifecycle_state, verification_status, object_schema_version,
                    content_version, provenance_json, embedding_refs_json, trust_snapshot_json,
                    metadata_json, relationship_summary_json, published_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    memory_id,
                    user_id,
                    source_type.value,
                    external_id,
                    canonical_url,
                    title,
                    source_author,
                    state.value,
                    verification.value,
                    1,
                    content_version,
                    prov.model_dump_json(),
                    emb.model_dump_json(),
                    trust_snapshot.model_dump_json() if trust_snapshot else "{}",
                    json.dumps(meta),
                    json.dumps(rel),
                    published_at,
                    created_at,
                    now,
                ),
            )
            if is_new:
                conn.execute(
                    """
                    INSERT INTO memory_lifecycle_events (
                        memory_id, user_id, from_state, to_state, reason, actor, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (memory_id, user_id, None, state.value, "created", "system", "{}", now),
                )

        memory = self.get(memory_id, user_id=user_id)
        assert memory is not None

        if increment_content_version:
            self.add_version(
                memory=memory,
                reason=version_reason or "content_updated",
            )
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
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                UPDATE memory_records
                SET lifecycle_state = ?, updated_at = ?
                WHERE memory_id = ? AND user_id = ?
                """,
                (to_state.value, now, memory_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO memory_lifecycle_events (
                    memory_id, user_id, from_state, to_state, reason, actor, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    user_id,
                    current.value if current else None,
                    to_state.value,
                    reason,
                    actor,
                    json.dumps(metadata or {}),
                    now,
                ),
            )
        updated = self.get(memory_id, user_id=user_id)
        assert updated is not None
        return updated

    def list_transitions(self, memory_id: str, *, limit: int = 50) -> list[LifecycleTransition]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_lifecycle_events
                WHERE memory_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (memory_id, limit),
            ).fetchall()
        return [_row_to_transition(row) for row in rows]

    def add_version(self, *, memory: UniversalMemory, reason: str = "") -> MemoryVersionSnapshot:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) AS max_v FROM memory_versions WHERE memory_id = ?",
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
                INSERT INTO memory_versions (
                    memory_id, user_id, version_number, lifecycle_state, verification_status,
                    trust_overall, title, reason, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.memory_id,
                    memory.user_id,
                    version_number,
                    memory.lifecycle_state.value,
                    memory.verification_status.value,
                    snapshot.trust_overall,
                    memory.title,
                    reason,
                    json.dumps(snapshot.snapshot),
                    now,
                ),
            )
        return snapshot

    def list_versions(self, memory_id: str, *, limit: int = 20) -> list[MemoryVersionSnapshot]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_versions
                WHERE memory_id = ?
                ORDER BY version_number DESC
                LIMIT ?
                """,
                (memory_id, limit),
            ).fetchall()
        out: list[MemoryVersionSnapshot] = []
        for row in rows:
            out.append(
                MemoryVersionSnapshot(
                    version_number=row["version_number"],
                    lifecycle_state=MemoryLifecycleState(row["lifecycle_state"]),
                    verification_status=VerificationStatus(row["verification_status"]),
                    trust_overall=row["trust_overall"],
                    title=row["title"],
                    reason=row["reason"],
                    created_at=row["created_at"],
                    snapshot=json.loads(row["snapshot_json"] or "{}"),
                )
            )
        return out

    def append_trust_history(
        self, *, memory_id: str, user_id: str, trust: TrustMetrics
    ) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO memory_trust_history (memory_id, user_id, trust_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (memory_id, user_id, trust.model_dump_json(), _utc_now()),
            )

    def list_trust_history(self, memory_id: str, *, limit: int = 20) -> list[TrustMetrics]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT trust_json FROM memory_trust_history
                WHERE memory_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (memory_id, limit),
            ).fetchall()
        return [TrustMetrics.model_validate_json(row["trust_json"]) for row in rows]


_STORES: dict[str, MemoryStore] = {}


def get_memory_store(settings: Settings | None = None) -> MemoryStore:
    settings = settings or get_settings()
    key = settings.sqlite_path
    if key not in _STORES:
        _STORES[key] = MemoryStore(settings)
    return _STORES[key]


def reset_memory_store_cache() -> None:
    _STORES.clear()


def _row_to_memory(row) -> UniversalMemory:
    trust_raw = row["trust_snapshot_json"] or "{}"
    trust = TrustMetrics.model_validate_json(trust_raw) if trust_raw.strip() not in ("", "{}") else None
    return UniversalMemory(
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        source_type=SourceType(row["source_type"]),
        external_id=row["external_id"],
        canonical_url=row["canonical_url"],
        title=row["title"],
        source_author=row["source_author"],
        lifecycle_state=MemoryLifecycleState(row["lifecycle_state"]),
        verification_status=VerificationStatus(row["verification_status"]),
        object_schema_version=row["object_schema_version"],
        content_version=row["content_version"],
        provenance=MemoryProvenance.model_validate_json(row["provenance_json"] or "{}"),
        embedding_refs=MemoryEmbeddingRefs.model_validate_json(row["embedding_refs_json"] or "{}"),
        trust=trust,
        metadata=json.loads(row["metadata_json"] or "{}"),
        relationship_summary=json.loads(row["relationship_summary_json"] or "{}"),
        published_at=row["published_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_transition(row) -> LifecycleTransition:
    from_state = row["from_state"]
    return LifecycleTransition(
        memory_id=row["memory_id"],
        from_state=MemoryLifecycleState(from_state) if from_state else None,
        to_state=MemoryLifecycleState(row["to_state"]),
        reason=row["reason"] or "",
        actor=row["actor"] or "system",
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
    )

"""Safe, tenant-explicit SQLite -> Postgres ingest-artifact migration for P-03.

Legacy ``content_hashes`` and ``memory_capsules_json`` rows do not carry tenant
identity. A caller must select the tenant explicitly, and tenant-bearing YouTube
or canonical memory rows must prove exclusive ownership for every artifact.
Missing, invalid, contradictory or multi-tenant ownership fails closed.

The SQLite source is opened read-only. Existing non-null Postgres artifact
fields are authoritative, so reruns only fill missing target fields and never
replace values already written after cutover.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from app.config import Settings, get_settings
from app.db.postgres_ingest_artifact_store import ensure_postgres_ingest_artifact_schema
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class IngestArtifactMigrationPreview:
    transcript_hashes: int
    capsules: int
    distinct_videos: int
    tenant: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class IngestArtifactMigrationReport:
    transcript_hashes_seen: int
    transcript_hashes_written: int
    transcript_hashes_skipped_existing: int
    capsules_seen: int
    capsules_written: int
    capsules_skipped_existing: int
    distinct_videos: int
    tenant: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


def preview_ingest_artifact_migration(
    settings: Settings | None = None,
    *,
    user_id: str,
) -> IngestArtifactMigrationPreview:
    """Validate ownership and return count-only source information."""
    tenant = _require_tenant(user_id)
    settings = settings or get_settings()
    with _open_source_read_only(settings) as source:
        transcript_rows, capsule_rows = _read_source_rows(source)
        video_ids = sorted({row["video_id"] for row in transcript_rows + capsule_rows})
        _validate_tenant_evidence(source, video_ids=video_ids, tenant=tenant)
    return IngestArtifactMigrationPreview(
        transcript_hashes=len(transcript_rows),
        capsules=len(capsule_rows),
        distinct_videos=len(video_ids),
        tenant=tenant,
    )


def migrate_ingest_artifacts_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str,
    connection_factory: ConnectionFactory | None = None,
) -> IngestArtifactMigrationReport:
    """Fill missing target artifact fields for exactly one validated tenant."""
    tenant = _require_tenant(user_id)
    settings = settings or get_settings()

    # Capture and validate the complete source snapshot before any target write.
    with _open_source_read_only(settings) as source:
        transcript_rows, capsule_rows = _read_source_rows(source)
        video_ids = sorted({row["video_id"] for row in transcript_rows + capsule_rows})
        _validate_tenant_evidence(source, video_ids=video_ids, tenant=tenant)

    factory = connection_factory or get_postgres_connection_factory(settings)
    ensure_postgres_ingest_artifact_schema(factory)

    transcript_written = 0
    capsule_written = 0
    with factory() as target:
        for row in transcript_rows:
            cur = target.execute(
                """
                INSERT INTO ingest_artifacts (
                    user_id, video_id, transcript_hash, capsule_json, updated_at
                ) VALUES (%s, %s, %s, NULL, %s)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    transcript_hash = EXCLUDED.transcript_hash
                WHERE ingest_artifacts.transcript_hash IS NULL
                """,
                (tenant, row["video_id"], row["transcript_hash"], row["updated_at"]),
            )
            transcript_written += max(int(cur.rowcount or 0), 0)

        for row in capsule_rows:
            cur = target.execute(
                """
                INSERT INTO ingest_artifacts (
                    user_id, video_id, transcript_hash, capsule_json, updated_at
                ) VALUES (%s, %s, NULL, %s, %s)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    capsule_json = EXCLUDED.capsule_json
                WHERE ingest_artifacts.capsule_json IS NULL
                """,
                (tenant, row["video_id"], row["capsule_json"], row["updated_at"]),
            )
            capsule_written += max(int(cur.rowcount or 0), 0)

    return IngestArtifactMigrationReport(
        transcript_hashes_seen=len(transcript_rows),
        transcript_hashes_written=transcript_written,
        transcript_hashes_skipped_existing=len(transcript_rows) - transcript_written,
        capsules_seen=len(capsule_rows),
        capsules_written=capsule_written,
        capsules_skipped_existing=len(capsule_rows) - capsule_written,
        distinct_videos=len(video_ids),
        tenant=tenant,
    )


def _read_source_rows(source: sqlite3.Connection) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    transcript_rows = source.execute(
        "SELECT video_id, transcript_hash, updated_at FROM content_hashes ORDER BY video_id"
    ).fetchall()
    capsule_rows = source.execute(
        "SELECT video_id, capsule_json, updated_at FROM memory_capsules_json ORDER BY video_id"
    ).fetchall()
    return transcript_rows, capsule_rows


def _validate_tenant_evidence(
    source: sqlite3.Connection,
    *,
    video_ids: list[str],
    tenant: str,
) -> None:
    """Reject source evidence that cannot belong exclusively to ``tenant``."""
    tables = {
        row["name"]
        for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for video_id in video_ids:
        evidence: list[sqlite3.Row] = []
        if "youtube_memories" in tables:
            evidence.extend(
                source.execute(
                    "SELECT DISTINCT user_id FROM youtube_memories WHERE video_id = ?",
                    (video_id,),
                ).fetchall()
            )
        if "memory_records" in tables:
            evidence.extend(
                source.execute(
                    """
                    SELECT DISTINCT user_id
                    FROM memory_records
                    WHERE external_id = ? AND source_type IN ('youtube', 'youtube.v1')
                    """,
                    (video_id,),
                ).fetchall()
            )
        if not evidence:
            raise ValueError("legacy ingest artifact ownership has no tenant-bearing proof")
        # Tenant IDs are identities, not display strings. Never coerce NULL or
        # normalize malformed evidence into a different tenant's identity.
        owners: set[str] = set()
        for row in evidence:
            owner = row["user_id"]
            if not isinstance(owner, str) or not owner or owner != owner.strip():
                raise ValueError("legacy ingest artifact ownership evidence is invalid")
            owners.add(owner)
        if len(owners) > 1:
            raise ValueError(
                "legacy ingest artifact ownership is ambiguous across multiple tenants"
            )
        if owners and tenant not in owners:
            raise ValueError(
                "selected user_id contradicts tenant-bearing source ownership evidence"
            )


def _require_tenant(user_id: str) -> str:
    tenant = user_id.strip()
    if not tenant:
        raise ValueError(
            "user_id is required because legacy ingest artifact tables have no tenant identity"
        )
    return tenant


@contextmanager
def _open_source_read_only(settings: Settings) -> Iterator[sqlite3.Connection]:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        # All artifact and ownership SELECTs must observe the same snapshot.
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()

"""Tenant-scoped Postgres persistence for deterministic ingest artifacts.

This P-03 primitive moves the small relational artifacts that ingestion still
writes directly to SQLite: transcript hashes used for unchanged-content checks
and serialized capsule JSON used for durable hierarchical-memory metadata.
Runtime routing is a separate acceptance slice so production cannot claim a
cutover before every call site is selected through one fail-closed boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.postgres_job_repository import ConnectionFactory


def ensure_postgres_ingest_artifact_schema(connection_factory: ConnectionFactory) -> None:
    """Create the tenant-scoped ingest artifact table idempotently."""
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_artifacts (
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                transcript_hash TEXT,
                capsule_json TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, video_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ingest_artifacts_tenant_hash
            ON ingest_artifacts(user_id, transcript_hash)
            """
        )


class PostgresIngestArtifactStore:
    """Persist transcript hashes and capsule JSON without cross-tenant identity."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connect = connection_factory
        ensure_postgres_ingest_artifact_schema(connection_factory)

    def transcript_unchanged(self, *, user_id: str, video_id: str, transcript_hash: str) -> bool:
        user_id = _required("user_id", user_id)
        video_id = _required("video_id", video_id)
        transcript_hash = _required("transcript_hash", transcript_hash)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT transcript_hash
                FROM ingest_artifacts
                WHERE user_id = %s AND video_id = %s
                """,
                (user_id, video_id),
            ).fetchone()
        return bool(row and row["transcript_hash"] == transcript_hash)

    def store_transcript_hash(self, *, user_id: str, video_id: str, transcript_hash: str) -> None:
        user_id = _required("user_id", user_id)
        video_id = _required("video_id", video_id)
        transcript_hash = _required("transcript_hash", transcript_hash)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_artifacts (
                    user_id, video_id, transcript_hash, capsule_json, updated_at
                ) VALUES (%s, %s, %s, NULL, %s)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    transcript_hash = EXCLUDED.transcript_hash,
                    updated_at = EXCLUDED.updated_at
                """,
                (user_id, video_id, transcript_hash, now),
            )

    def store_capsule_json(self, *, user_id: str, video_id: str, capsule_json: str) -> None:
        user_id = _required("user_id", user_id)
        video_id = _required("video_id", video_id)
        capsule_json = _required("capsule_json", capsule_json)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_artifacts (
                    user_id, video_id, transcript_hash, capsule_json, updated_at
                ) VALUES (%s, %s, NULL, %s, %s)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    capsule_json = EXCLUDED.capsule_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (user_id, video_id, capsule_json, now),
            )


def _required(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized

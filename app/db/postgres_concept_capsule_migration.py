"""Safe, idempotent SQLite to Postgres migration for concept capsules."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.intelligence_store import normalize_topic
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_concept_capsule_store import PostgresConceptCapsuleStore
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class ConceptCapsuleMigrationPreview:
    capsules: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ConceptCapsuleMigrationReport:
    capsules_seen: int
    capsules_inserted: int
    capsules_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_concept_capsule_migration(
    settings: Settings | None = None, *, user_id: str | None = None
) -> ConceptCapsuleMigrationPreview:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as conn:
        capsules = int(conn.execute(f"SELECT COUNT(*) FROM concept_capsules{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM concept_capsules{where}", params
            ).fetchone()[0]
        )
    return ConceptCapsuleMigrationPreview(capsules=capsules, tenants=tenants)


def migrate_concept_capsules_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> ConceptCapsuleMigrationReport:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresConceptCapsuleStore(factory)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as source:
        rows = source.execute(
            "SELECT capsule_id,user_id,name,normalized_name,summary,topic_ids_json,"
            "memory_video_ids_json,creator_names_json,progress_total,progress_completed,updated_at "
            f"FROM concept_capsules{where} "
            "ORDER BY user_id, normalized_name, capsule_id",
            params,
        ).fetchall()

    _validate_source_rows(rows)

    inserted = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """INSERT INTO concept_capsules (
                    capsule_id,user_id,name,normalized_name,summary,topic_ids_json,
                    memory_video_ids_json,creator_names_json,progress_total,
                    progress_completed,updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING""",
                tuple(row),
            )
            inserted += max(int(cur.rowcount or 0), 0)

    return ConceptCapsuleMigrationReport(
        capsules_seen=len(rows),
        capsules_inserted=inserted,
        capsules_skipped_existing=len(rows) - inserted,
    )


def _validate_source_rows(rows: list[sqlite3.Row]) -> None:
    identities: set[tuple[str, str]] = set()
    capsule_ids: set[str] = set()
    json_list_fields = ("topic_ids_json", "memory_video_ids_json", "creator_names_json")
    for row in rows:
        capsule_id = str(row["capsule_id"] or "").strip()
        user_id = str(row["user_id"] or "").strip()
        name = str(row["name"] or "").strip()
        normalized_name = str(row["normalized_name"] or "").strip()
        if not capsule_id or not user_id or not name or not normalized_name:
            raise ValueError("concept capsule contains a blank identity")
        if normalize_topic(name) != normalized_name:
            raise ValueError("concept capsule normalized_name does not match name")
        total = int(row["progress_total"])
        completed = int(row["progress_completed"])
        if total < 0 or completed < 0 or completed > total:
            raise ValueError("concept capsule contains invalid progress bounds")
        for field in json_list_fields:
            try:
                value = json.loads(row[field] or "[]")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"concept capsule contains invalid {field}") from exc
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"concept capsule {field} must be a list of strings")
        identity = (user_id, normalized_name)
        if identity in identities:
            raise ValueError("concept capsule source contains duplicate tenant identity")
        if capsule_id in capsule_ids:
            raise ValueError("concept capsule source contains duplicate capsule_id")
        identities.add(identity)
        capsule_ids.add(capsule_id)


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _normalize_user_id(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    value = user_id.strip()
    if not value:
        raise ValueError("user_id must not be blank")
    return value


def _tenant_filter(user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    return ("", ()) if user_id is None else (" WHERE user_id = ?", (user_id,))

"""Safe, idempotent SQLite to Postgres migration for learning edges."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_learning_edge_store import PostgresLearningEdgeStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.models.intelligence import LearningRelation


@dataclass(frozen=True)
class LearningEdgeMigrationPreview:
    edges: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class LearningEdgeMigrationReport:
    edges_seen: int
    edges_inserted: int
    edges_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_learning_edge_migration(
    settings: Settings | None = None, *, user_id: str | None = None
) -> LearningEdgeMigrationPreview:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as conn:
        edges = int(conn.execute(f"SELECT COUNT(*) FROM learning_edges{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM learning_edges{where}", params
            ).fetchone()[0]
        )
    return LearningEdgeMigrationPreview(edges=edges, tenants=tenants)


def migrate_learning_edges_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> LearningEdgeMigrationReport:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresLearningEdgeStore(factory)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as source:
        rows = source.execute(
            "SELECT edge_id,user_id,source_video_id,target_video_id,relation,strength,"
            "evidence,evidence_refs_json,created_at "
            f"FROM learning_edges{where} "
            "ORDER BY user_id, source_video_id, target_video_id, relation, edge_id",
            params,
        ).fetchall()

    _validate_source_rows(rows)

    inserted = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """INSERT INTO learning_edges (
                    edge_id,user_id,source_video_id,target_video_id,relation,
                    strength,evidence,evidence_refs_json,created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING""",
                tuple(row),
            )
            inserted += max(int(cur.rowcount or 0), 0)

    return LearningEdgeMigrationReport(
        edges_seen=len(rows),
        edges_inserted=inserted,
        edges_skipped_existing=len(rows) - inserted,
    )


def _validate_source_rows(rows: list[sqlite3.Row]) -> None:
    valid_relations = {relation.value for relation in LearningRelation}
    identities: set[tuple[str, str, str, str]] = set()
    for row in rows:
        user_id = str(row["user_id"] or "").strip()
        source_video_id = str(row["source_video_id"] or "").strip()
        target_video_id = str(row["target_video_id"] or "").strip()
        relation = str(row["relation"] or "").strip()
        if not user_id or not source_video_id or not target_video_id:
            raise ValueError("learning edge contains a blank tenant or video identity")
        if source_video_id == target_video_id:
            raise ValueError("learning edge source contains a self-edge")
        if relation not in valid_relations:
            raise ValueError(f"learning edge contains unknown relation: {relation}")
        try:
            refs = json.loads(row["evidence_refs_json"] or "[]")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("learning edge contains invalid evidence_refs_json") from exc
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("learning edge evidence_refs_json must be a list of strings")
        identity = (user_id, source_video_id, target_video_id, relation)
        if identity in identities:
            raise ValueError("learning edge source contains duplicate tenant identity")
        identities.add(identity)


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

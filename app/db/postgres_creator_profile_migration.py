"""Safe, idempotent SQLite to Postgres migration for creator profiles."""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.intelligence_store import normalize_topic
from app.db.postgres_creator_profile_store import PostgresCreatorProfileStore
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class CreatorProfileMigrationPreview:
    creators: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class CreatorProfileMigrationReport:
    creators_seen: int
    creators_inserted: int
    creators_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_creator_profile_migration(
    settings: Settings | None = None, *, user_id: str | None = None
) -> CreatorProfileMigrationPreview:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as conn:
        creators = int(conn.execute(f"SELECT COUNT(*) FROM creator_profiles{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM creator_profiles{where}", params
            ).fetchone()[0]
        )
    return CreatorProfileMigrationPreview(creators=creators, tenants=tenants)


def migrate_creator_profiles_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> CreatorProfileMigrationReport:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresCreatorProfileStore(factory)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as source:
        rows = source.execute(
            "SELECT creator_id,user_id,name,normalized_name,channel_id,video_count,"
            "topics_json,total_duration_sec,avg_duration_sec,beginner_count,advanced_count,"
            "view_count,helpful_count,related_creators_json,updated_at "
            f"FROM creator_profiles{where} "
            "ORDER BY user_id, normalized_name, creator_id",
            params,
        ).fetchall()

    _validate_source_rows(rows)

    inserted = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """INSERT INTO creator_profiles (
                    creator_id,user_id,name,normalized_name,channel_id,video_count,
                    topics_json,total_duration_sec,avg_duration_sec,beginner_count,
                    advanced_count,view_count,helpful_count,related_creators_json,updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING""",
                tuple(row),
            )
            inserted += max(int(cur.rowcount or 0), 0)

    return CreatorProfileMigrationReport(
        creators_seen=len(rows),
        creators_inserted=inserted,
        creators_skipped_existing=len(rows) - inserted,
    )


def _validate_source_rows(rows: list[sqlite3.Row]) -> None:
    identities: set[tuple[str, str]] = set()
    creator_ids: set[str] = set()
    for row in rows:
        creator_id = str(row["creator_id"] or "").strip()
        user_id = str(row["user_id"] or "").strip()
        name = str(row["name"] or "").strip()
        normalized_name = str(row["normalized_name"] or "").strip()
        if not creator_id or not user_id or not name or not normalized_name:
            raise ValueError("creator profile contains a blank identity")
        if (normalize_topic(name) or "unknown") != normalized_name:
            raise ValueError("creator profile normalized_name does not match name")

        video_count = int(row["video_count"])
        beginner_count = int(row["beginner_count"])
        advanced_count = int(row["advanced_count"])
        view_count = int(row["view_count"])
        helpful_count = int(row["helpful_count"])
        total_duration = float(row["total_duration_sec"])
        average_duration = float(row["avg_duration_sec"])
        if min(video_count, beginner_count, advanced_count, view_count, helpful_count) < 0:
            raise ValueError("creator profile contains a negative aggregate")
        if beginner_count > video_count or advanced_count > video_count:
            raise ValueError("creator profile contains invalid coverage counts")
        if not math.isfinite(total_duration) or not math.isfinite(average_duration):
            raise ValueError("creator profile contains non-finite duration")
        if total_duration < 0 or average_duration < 0:
            raise ValueError("creator profile contains a negative duration")
        expected_average = total_duration / max(video_count, 1)
        if not math.isclose(average_duration, expected_average, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("creator profile average duration does not match aggregate")

        for field in ("topics_json", "related_creators_json"):
            try:
                value = json.loads(row[field] or "[]")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"creator profile contains invalid {field}") from exc
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"creator profile {field} must be a list of strings")

        identity = (user_id, normalized_name)
        if identity in identities:
            raise ValueError("creator profile source contains duplicate tenant identity")
        if creator_id in creator_ids:
            raise ValueError("creator profile source contains duplicate creator_id")
        identities.add(identity)
        creator_ids.add(creator_id)


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

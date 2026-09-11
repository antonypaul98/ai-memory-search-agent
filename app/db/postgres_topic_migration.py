"""Safe, idempotent SQLite to Postgres migration for Memory Intelligence topics."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_topic_store import PostgresTopicStore


@dataclass(frozen=True)
class TopicMigrationPreview:
    topics: int
    links: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class TopicMigrationReport:
    topics_seen: int
    topics_inserted: int
    topics_skipped_existing: int
    links_seen: int
    links_inserted: int
    links_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_topic_migration(
    settings: Settings | None = None, *, user_id: str | None = None
) -> TopicMigrationPreview:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as conn:
        topics = int(conn.execute(f"SELECT COUNT(*) FROM topic_profiles{where}", params).fetchone()[0])
        links = int(conn.execute(f"SELECT COUNT(*) FROM topic_memory_links{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(f"SELECT COUNT(DISTINCT user_id) FROM topic_profiles{where}", params).fetchone()[0]
        )
    return TopicMigrationPreview(topics=topics, links=links, tenants=tenants)


def migrate_topics_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> TopicMigrationReport:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresTopicStore(factory)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as source:
        topics = source.execute(
            "SELECT topic_id,user_id,name,normalized_name,category,summary,memory_count,"
            "first_seen_at,last_seen_at,last_updated_at,evidence_json "
            f"FROM topic_profiles{where} ORDER BY user_id, normalized_name, topic_id",
            params,
        ).fetchall()
        links = source.execute(
            "SELECT topic_id,user_id,video_id,memory_id,strength,evidence "
            f"FROM topic_memory_links{where} ORDER BY user_id, topic_id, video_id",
            params,
        ).fetchall()

    topic_tenants = {row["topic_id"]: row["user_id"] for row in topics}
    for row in links:
        owner = topic_tenants.get(row["topic_id"])
        if owner is None or owner != row["user_id"]:
            raise ValueError("topic link ownership does not match a selected topic profile")

    inserted_topics = 0
    inserted_links = 0
    with factory() as target:
        for row in topics:
            cur = target.execute(
                """INSERT INTO topic_profiles (
                    topic_id,user_id,name,normalized_name,category,summary,memory_count,
                    first_seen_at,last_seen_at,last_updated_at,evidence_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING""",
                tuple(row),
            )
            inserted_topics += max(int(cur.rowcount or 0), 0)
        for row in links:
            cur = target.execute(
                """INSERT INTO topic_memory_links (
                    topic_id,user_id,video_id,memory_id,strength,evidence
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT(topic_id, video_id) DO NOTHING""",
                tuple(row),
            )
            inserted_links += max(int(cur.rowcount or 0), 0)

    return TopicMigrationReport(
        topics_seen=len(topics),
        topics_inserted=inserted_topics,
        topics_skipped_existing=len(topics) - inserted_topics,
        links_seen=len(links),
        links_inserted=inserted_links,
        links_skipped_existing=len(links) - inserted_links,
    )


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

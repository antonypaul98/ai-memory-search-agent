"""Cross-connector duplicate detection via canonical URL and content hash."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate
from app.services.deduplication_service import hash_text


@dataclass
class CrossDuplicateReport:
    is_duplicate: bool
    reason: str = ""
    match_type: str = "none"  # url | content_hash | none
    existing_source_type: str = ""
    existing_external_id: str = ""
    existing_connector_id: str = ""
    existing_memory_id: str | None = None


class CrossConnectorDuplicateDetector:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    def check(
        self,
        *,
        user_id: str,
        canonical_url: str,
        content_hash: str = "",
    ) -> CrossDuplicateReport:
        url_hash = hash_text(canonical_url.strip())
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM content_url_index
                WHERE user_id = ? AND url_hash = ?
                """,
                (user_id, url_hash),
            ).fetchone()
            if row:
                return CrossDuplicateReport(
                    is_duplicate=True,
                    reason=f"Same canonical URL already saved via {row['connector_id']}",
                    match_type="url",
                    existing_source_type=row["source_type"],
                    existing_external_id=row["external_id"],
                    existing_connector_id=row["connector_id"],
                    existing_memory_id=row["memory_id"],
                )
            if content_hash:
                row = conn.execute(
                    """
                    SELECT * FROM content_url_index
                    WHERE user_id = ? AND content_hash = ? AND content_hash != ''
                    LIMIT 1
                    """,
                    (user_id, content_hash),
                ).fetchone()
                if row:
                    return CrossDuplicateReport(
                        is_duplicate=True,
                        reason=f"Same content hash already saved via {row['connector_id']}",
                        match_type="content_hash",
                        existing_source_type=row["source_type"],
                        existing_external_id=row["external_id"],
                        existing_connector_id=row["connector_id"],
                        existing_memory_id=row["memory_id"],
                    )
        return CrossDuplicateReport(is_duplicate=False)

    def register(
        self,
        *,
        user_id: str,
        canonical_url: str,
        content_hash: str,
        source_type: str,
        connector_id: str,
        external_id: str,
        memory_id: str | None = None,
    ) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        url_hash = hash_text(canonical_url.strip())
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO content_url_index (
                    user_id, url_hash, canonical_url, content_hash,
                    source_type, connector_id, external_id, memory_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, url_hash) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    source_type = excluded.source_type,
                    connector_id = excluded.connector_id,
                    external_id = excluded.external_id,
                    memory_id = excluded.memory_id
                """,
                (
                    user_id,
                    url_hash,
                    canonical_url,
                    content_hash or "",
                    source_type,
                    connector_id,
                    external_id,
                    memory_id,
                    now,
                ),
            )

    def known_url_hashes(self, user_id: str) -> set[str]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                "SELECT url_hash FROM content_url_index WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {r["url_hash"] for r in rows}

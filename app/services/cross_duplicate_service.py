"""Cross-connector duplicate detection via canonical URL and content hash."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.db.content_url_index_store_factory import get_content_url_index_store
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
        self._store = get_content_url_index_store(self._settings)

    def check(
        self,
        *,
        user_id: str,
        canonical_url: str,
        content_hash: str = "",
    ) -> CrossDuplicateReport:
        url_hash = hash_text(canonical_url.strip())
        row = self._store.find_by_url_hash(user_id=user_id, url_hash=url_hash)
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
            row = self._store.find_by_content_hash(user_id=user_id, content_hash=content_hash)
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
        self._store.register(
            user_id=user_id,
            url_hash=hash_text(canonical_url.strip()),
            canonical_url=canonical_url,
            content_hash=content_hash,
            source_type=source_type,
            connector_id=connector_id,
            external_id=external_id,
            memory_id=memory_id,
        )

    def known_url_hashes(self, user_id: str) -> set[str]:
        return self._store.known_url_hashes(user_id=user_id)

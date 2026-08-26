"""Idempotent migration for legacy Chroma chunks without tenant metadata."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.db.chroma_client import get_collection
from app.models.user import LOCAL_DEFAULT_USER_ID


@dataclass(frozen=True)
class LegacyUserBackfillResult:
    scanned: int
    legacy_found: int
    updated: int
    dry_run: bool


def backfill_legacy_user_ids(
    settings: Settings | None = None,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
) -> LegacyUserBackfillResult:
    """Assign pre-tenant Chroma rows to ``local-default`` in place.

    The migration intentionally does not re-embed or replace documents. It only
    adds the missing ``user_id`` metadata field, preserving ids, vectors,
    documents, provenance and every other metadata value. Existing tenant-owned
    rows are never modified.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    runtime_settings = settings or get_settings()
    collection = get_collection(runtime_settings)

    scanned = 0
    legacy_found = 0
    updated = 0
    offset = 0

    while True:
        page = collection.get(
            limit=batch_size,
            offset=offset,
            include=["metadatas"],
        )
        ids = list(page.get("ids") or [])
        metadatas = list(page.get("metadatas") or [])
        if not ids:
            break

        scanned += len(ids)
        update_ids: list[str] = []
        update_metadatas: list[dict] = []

        for item_id, metadata in zip(ids, metadatas):
            meta = dict(metadata or {})
            if meta.get("user_id"):
                continue
            legacy_found += 1
            meta["user_id"] = LOCAL_DEFAULT_USER_ID
            update_ids.append(str(item_id))
            update_metadatas.append(meta)

        if update_ids and not dry_run:
            collection.update(ids=update_ids, metadatas=update_metadatas)
            updated += len(update_ids)

        offset += len(ids)
        if len(ids) < batch_size:
            break

    return LegacyUserBackfillResult(
        scanned=scanned,
        legacy_found=legacy_found,
        updated=updated,
        dry_run=dry_run,
    )

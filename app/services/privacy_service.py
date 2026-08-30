"""Privacy controls: portable export and hard-delete of user-owned memories (V1-8)."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.hierarchical_store import HierarchicalStore
from app.db.memory_store import get_memory_store
from app.db.repositories.memory_repository import MemoryRepository
from app.db.schema import bump_index_version, get_connection, migrate
from app.db.video_registry import get_video_registry
from app.services.fts_index import FTSIndex

logger = logging.getLogger(__name__)

_EXPORT_PAYLOAD_START = "<!-- AI_MEMORY_EXPORT_JSON_V1:"
_EXPORT_PAYLOAD_END = ":AI_MEMORY_EXPORT_JSON_V1 -->"
_MAX_MARKDOWN_IMPORT_BYTES = 50_000_000


class PrivacyService:
    """User-scoped export and deletion for store / GDPR-style controls."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)
        self._memory_store = get_memory_store(self._settings)
        self._repo = MemoryRepository(self._settings)
        self._registry = get_video_registry(self._settings)
        self._fts = FTSIndex(self._settings)
        self._hstore = HierarchicalStore(self._settings)

    def export_user_data(self, *, user_id: str) -> dict[str, Any]:
        memories = self._memory_store.list_recent(user_id=user_id, limit=10_000)
        with get_connection(self._settings) as conn:
            user_row = conn.execute(
                "SELECT user_id, email, display_name, created_at FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            youtube = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM youtube_memories WHERE user_id = ? ORDER BY saved_at DESC",
                    (user_id,),
                ).fetchall()
            ]
            captures = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM captures WHERE user_id = ? ORDER BY created_at DESC LIMIT 2000",
                    (user_id,),
                ).fetchall()
            ]
            bookmarks = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM browser_bookmarks WHERE user_id = ? ORDER BY id DESC LIMIT 5000",
                    (user_id,),
                ).fetchall()
            ]
            jobs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM background_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 500",
                    (user_id,),
                ).fetchall()
            ]
            topics = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM topic_profiles WHERE user_id = ? ORDER BY last_updated_at DESC",
                    (user_id,),
                ).fetchall()
            ]

        return {
            "export_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user": dict(user_row) if user_row else {"user_id": user_id},
            "memories": [m.model_dump(mode="json") for m in memories],
            "youtube_memories": youtube,
            "captures": captures,
            "browser_bookmarks": bookmarks,
            "jobs": jobs,
            "topics": topics,
            "video_registry": self._registry.list_videos(user_id=user_id),
        }

    def delete_memory(self, *, memory_id: str, user_id: str) -> dict[str, Any]:
        memory = self._memory_store.get(memory_id, user_id=user_id)
        if not memory:
            raise KeyError(f"Memory not found: {memory_id}")

        external_id = memory.external_id
        source_type = (
            memory.source_type.value
            if hasattr(memory.source_type, "value")
            else str(memory.source_type)
        )

        # Vector evidence (user-scoped).
        self._repo.delete_item(external_id, user_id=user_id)

        # Shared FTS / hierarchical / capsule indexes — only if no other tenant shares the id.
        shared = self._registry.other_users_have_video(external_id, excluding_user_id=user_id)
        if not shared:
            try:
                self._fts.delete_video(external_id)
            except Exception:
                logger.debug("fts delete skipped for %s", external_id, exc_info=True)
            try:
                self._hstore.delete_video(external_id)
            except Exception:
                logger.debug("hierarchical delete skipped for %s", external_id, exc_info=True)

        self._registry.delete_video(external_id, user_id=user_id)
        self._delete_sqlite_memory_rows(
            memory_id=memory_id,
            user_id=user_id,
            external_id=external_id,
            source_type=source_type,
            delete_shared_capsule=not shared,
        )
        bump_index_version(self._settings)
        logger.info(
            "memory_deleted memory_id=%s user_id=%s external_id=%s",
            memory_id,
            user_id,
            external_id,
        )
        return {
            "deleted": True,
            "memory_id": memory_id,
            "external_id": external_id,
            "source_type": source_type,
        }

    def delete_all_memories(self, *, user_id: str) -> dict[str, Any]:
        memories = self._memory_store.list_recent(user_id=user_id, limit=50_000)
        deleted = 0
        errors: list[str] = []
        for memory in memories:
            try:
                self.delete_memory(memory_id=memory.memory_id, user_id=user_id)
                deleted += 1
            except Exception as exc:
                errors.append(f"{memory.memory_id}: {exc}")
        return {"deleted_count": deleted, "errors": errors}

    def _delete_sqlite_memory_rows(
        self,
        *,
        memory_id: str,
        user_id: str,
        external_id: str,
        source_type: str,
        delete_shared_capsule: bool = True,
    ) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                "DELETE FROM kg_memory_entities WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM topic_memory_links WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM memory_trust_history WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM memory_versions WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM memory_lifecycle_events WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM memory_records WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.execute(
                "DELETE FROM youtube_memories WHERE user_id = ? AND video_id = ?",
                (user_id, external_id),
            )
            conn.execute(
                """
                DELETE FROM content_url_index
                WHERE user_id = ? AND source_type = ? AND external_id = ?
                """,
                (user_id, source_type, external_id),
            )
            # Capsules are keyed only by video_id — never drop while another tenant
            # still references the same external id (bump_index_version invalidates cache).
            if delete_shared_capsule:
                conn.execute(
                    "DELETE FROM memory_capsules_json WHERE video_id = ?",
                    (external_id,),
                )


def dump_export_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)


def dump_export_markdown(payload: dict[str, Any]) -> str:
    """Render the complete tenant export as portable, deterministic Markdown.

    Human-readable summaries remain first. A hidden, versioned, base64-encoded JSON
    payload is appended so the Markdown artifact is losslessly re-importable without
    parsing presentation text or dropping connector-specific/private fields.
    """

    user = payload.get("user") or {}
    memories = list(payload.get("memories") or [])
    title_owner = user.get("display_name") or user.get("email") or user.get("user_id") or "User"
    lines = [
        "# AI Memory Export",
        "",
        f"- Owner: {_md_inline(title_owner)}",
        f"- Exported at: {_md_inline(payload.get('exported_at') or '')}",
        f"- Export version: {_md_inline(payload.get('export_version') or '')}",
        f"- Memories: {len(memories)}",
        "",
        "## Memories",
        "",
    ]

    if not memories:
        lines.extend(["_No memories exported._", ""])
    else:
        for memory in memories:
            title = memory.get("title") or memory.get("external_id") or memory.get("memory_id") or "Untitled memory"
            lines.extend(
                [
                    f"### {_md_inline(title)}",
                    "",
                    f"- Source: {_md_inline(memory.get('source_type') or '')}",
                    f"- Author: {_md_inline(memory.get('source_author') or '')}",
                    f"- URL: {_md_inline(memory.get('canonical_url') or '')}",
                    f"- Memory ID: {_md_inline(memory.get('memory_id') or '')}",
                    f"- External ID: {_md_inline(memory.get('external_id') or '')}",
                    f"- Lifecycle: {_md_inline(memory.get('lifecycle_state') or '')}",
                    f"- Verification: {_md_inline(memory.get('verification_status') or '')}",
                    f"- Created: {_md_inline(memory.get('created_at') or '')}",
                    f"- Updated: {_md_inline(memory.get('updated_at') or '')}",
                ]
            )
            trust = memory.get("trust") or memory.get("trust_snapshot") or {}
            if isinstance(trust, dict) and trust:
                tier = trust.get("tier") or ""
                overall = trust.get("overall")
                trust_text = tier if overall is None else f"{tier} ({overall})"
                lines.append(f"- Trust: {_md_inline(trust_text)}")
            metadata = memory.get("metadata") or {}
            if isinstance(metadata, dict):
                if metadata.get("save_reason"):
                    lines.append(f"- Why saved: {_md_inline(metadata['save_reason'])}")
                if metadata.get("user_goal"):
                    lines.append(f"- Goal: {_md_inline(metadata['user_goal'])}")
            lines.extend(["", "Record data:", "", *_indented_json(memory), ""])

    collection_labels = (
        ("youtube_memories", "YouTube memories"),
        ("captures", "Captures"),
        ("browser_bookmarks", "Browser bookmarks"),
        ("jobs", "Background jobs"),
        ("topics", "Topics"),
        ("video_registry", "Video registry"),
    )
    for key, label in collection_labels:
        value = payload.get(key) or []
        lines.extend(
            [
                f"## {label}",
                "",
                f"Count: {len(value) if isinstance(value, list) else 1}",
                "",
                *_indented_json(value),
                "",
            ]
        )

    # Preserve the user record as exported too, not only the display fields above.
    lines.extend(["## User record", "", *_indented_json(user), ""])
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    lines.extend([_EXPORT_PAYLOAD_START + encoded_payload + _EXPORT_PAYLOAD_END, ""])
    return "\n".join(lines).rstrip() + "\n"


def load_export_markdown(markdown: str) -> dict[str, Any]:
    """Recover the lossless export payload embedded by ``dump_export_markdown``.

    This is deliberately a pure import-adapter boundary: it validates and restores
    portable data but performs no writes. A caller must still apply normal tenant,
    deduplication, provenance, and confirmation rules before importing records.
    """

    raw = markdown.encode("utf-8")
    if len(raw) > _MAX_MARKDOWN_IMPORT_BYTES:
        raise ValueError("Markdown export exceeds import size limit")

    start = markdown.rfind(_EXPORT_PAYLOAD_START)
    if start < 0:
        raise ValueError("Markdown export payload marker is missing")
    start += len(_EXPORT_PAYLOAD_START)
    end = markdown.find(_EXPORT_PAYLOAD_END, start)
    if end < 0:
        raise ValueError("Markdown export payload marker is incomplete")

    encoded = markdown[start:end].strip().encode("ascii")
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Markdown export payload is invalid") from exc

    if not isinstance(payload, dict) or payload.get("export_version") != 1:
        raise ValueError("Unsupported Markdown export payload")
    return payload


def _md_inline(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")


def _indented_json(value: Any) -> list[str]:
    return [f"    {line}" for line in json.dumps(value, indent=2, default=str, sort_keys=True).splitlines()]

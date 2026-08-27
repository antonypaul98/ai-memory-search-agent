"""Readwise CSV import bridge.

Groups individual highlight rows into one article/book memory and delegates indexing
to the existing connector ingest pipeline. No external Readwise credentials are
required for CSV exports.
"""

from __future__ import annotations

import csv
import io
from collections import OrderedDict

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.reflection import ReflectionInput, SaveReason
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.deduplication_service import hash_text


class ReadwiseImportService:
    def __init__(self, settings: Settings | None = None, ingest_service: ConnectorIngestService | None = None) -> None:
        self._settings = settings or get_settings()
        self._ingest = ingest_service or ConnectorIngestService(self._settings)

    def parse_csv(self, data: bytes) -> list[dict]:
        if not data:
            raise AppError("Readwise CSV is empty.")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppError("Readwise CSV must be UTF-8 encoded.") from exc

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise AppError("Readwise CSV is missing a header row.")
        fields = {str(name).strip().lower() for name in reader.fieldnames if name}
        if "highlight" not in fields or "title" not in fields:
            raise AppError("Readwise CSV must include Highlight and Title columns.")

        groups: OrderedDict[str, dict] = OrderedDict()
        for row in reader:
            clean = {str(k).strip().lower(): (v or "").strip() for k, v in row.items() if k}
            highlight = clean.get("highlight", "")
            title = clean.get("title", "")
            if not highlight or not title:
                continue
            author = clean.get("author", "")
            url = clean.get("url", "")
            grouping_key = url.lower() if url.startswith(("http://", "https://")) else f"{title.lower()}|{author.lower()}"
            external_id = hash_text(grouping_key)[:24]
            group = groups.setdefault(
                external_id,
                {
                    "external_id": external_id,
                    "title": title,
                    "author": author,
                    "canonical_url": url,
                    "highlights": [],
                    "notes": [],
                    "locations": [],
                    "tags": [],
                },
            )
            group["highlights"].append(highlight)
            group["notes"].append(clean.get("note", ""))
            group["locations"].append(clean.get("location", ""))
            for raw_tags in (clean.get("tags", ""), clean.get("document tags", "")):
                for tag in _split_tags(raw_tags):
                    if tag not in group["tags"]:
                        group["tags"].append(tag)
        if not groups:
            raise AppError("Readwise CSV contains no importable highlights.")
        return list(groups.values())

    def preview_csv(self, data: bytes) -> dict:
        groups = self.parse_csv(data)
        return {
            "article_count": len(groups),
            "highlight_count": sum(len(group["highlights"]) for group in groups),
            "articles": [
                {
                    "external_id": group["external_id"],
                    "title": group["title"],
                    "author": group["author"],
                    "highlight_count": len(group["highlights"]),
                    "tags": list(group["tags"]),
                }
                for group in groups[:100]
            ],
        }

    def ingest_csv(self, data: bytes, *, user_id: str, force_refresh: bool = False) -> dict:
        groups = self.parse_csv(data)
        results = []
        for group in groups:
            tags = list(group["tags"])
            reflection = ReflectionInput(
                save_reason=SaveReason.REFERENCE,
                reflection_note=(f"Imported from Readwise. Tags: {', '.join(tags)}" if tags else "Imported from Readwise."),
            )
            result = self._ingest.ingest_url(
                f"readwise://article/{group['external_id']}",
                user_id=user_id,
                force_refresh=force_refresh,
                reflection=reflection,
                connector_id="readwise.v1",
                ref_extra=group,
            )
            results.append(result)
        return {
            "article_count": len(groups),
            "highlight_count": sum(len(group["highlights"]) for group in groups),
            "succeeded": sum(1 for result in results if result.success and not result.skipped),
            "skipped": sum(1 for result in results if result.skipped),
            "failed": sum(1 for result in results if not result.success),
            "results": [result.model_dump(mode="json") for result in results],
        }


def _split_tags(raw: str) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace(";", ",")
    return [part.strip().lstrip("#") for part in normalized.split(",") if part.strip().lstrip("#")]

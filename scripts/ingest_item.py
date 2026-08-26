"""CLI helper to ingest a single YouTube URL into AI Memory Search Agent.

Examples:
    python scripts/ingest_item.py https://www.youtube.com/watch?v=...
    python scripts/ingest_item.py <url> --force-refresh
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable

from app.services.ingest_service import IngestService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest one YouTube URL into memory.")
    parser.add_argument("url", help="YouTube video URL to ingest.")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-fetch and re-index the item even if it already exists.",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Optional user id. Defaults to the application's local user behavior.",
    )
    return parser


def _as_dict(result: object) -> dict:
    if hasattr(result, "model_dump"):
        return result.model_dump()  # type: ignore[no-any-return, attr-defined]
    if hasattr(result, "dict"):
        return result.dict()  # type: ignore[no-any-return, attr-defined]
    return dict(vars(result))


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)

    try:
        result = IngestService().ingest_single_url(
            args.url,
            user_id=args.user_id,
            force_refresh=args.force_refresh,
        )
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    payload = _as_dict(result)
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0 if bool(payload.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

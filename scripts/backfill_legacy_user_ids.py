"""Backfill legacy Chroma chunks with the local-default tenant id.

Usage:
  python scripts/backfill_legacy_user_ids.py --dry-run
  python scripts/backfill_legacy_user_ids.py --yes
"""

from __future__ import annotations

import argparse
import json

from app.services.legacy_user_backfill import backfill_legacy_user_ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assign legacy Chroma rows without user_id to local-default."
    )
    parser.add_argument("--dry-run", action="store_true", help="Scan only; make no changes.")
    parser.add_argument("--yes", action="store_true", help="Confirm the metadata update.")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dry_run and not args.yes:
        print(json.dumps({"ok": False, "error": "confirmation_required"}))
        return 2

    try:
        result = backfill_legacy_user_ids(batch_size=args.batch_size, dry_run=args.dry_run)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "scanned": result.scanned,
                "legacy_found": result.legacy_found,
                "updated": result.updated,
                "dry_run": result.dry_run,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

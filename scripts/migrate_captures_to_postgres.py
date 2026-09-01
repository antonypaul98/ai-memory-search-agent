#!/usr/bin/env python3
"""Preview or explicitly apply the P-03 capture-state Postgres migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.postgres_capture_migration import (
    migrate_captures_to_postgres,
    preview_capture_migration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview SQLite capture rows or explicitly insert missing rows into the "
            "configured Postgres target. Existing target rows are preserved."
        )
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Optional exact tenant to migrate. Omit to migrate every tenant in the source.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform target writes. Without this flag the command is preview-only.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    settings = get_settings()

    preview = preview_capture_migration(settings, user_id=args.user_id)
    if not args.apply:
        print(json.dumps({"mode": "preview", **preview.to_dict()}, sort_keys=True))
        return 0

    report = migrate_captures_to_postgres(settings, user_id=args.user_id)
    print(json.dumps({"mode": "applied", **report.to_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Preview or explicitly apply the P-03 ingest-artifact Postgres migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.postgres_ingest_artifact_migration import (
    migrate_ingest_artifacts_to_postgres,
    preview_ingest_artifact_migration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview legacy transcript-hash/capsule rows or explicitly fill missing "
            "fields in the configured Postgres target. Legacy artifact rows have no "
            "tenant column, so an exact tenant selection and ownership proof are required; missing or conflicting "
            "tenant-bearing source evidence fails closed."
        )
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="Exact tenant selected for this legacy SQLite artifact source.",
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
    preview = preview_ingest_artifact_migration(settings, user_id=args.user_id)
    if not args.apply:
        print(json.dumps({"mode": "preview", **preview.to_dict()}, sort_keys=True))
        return 0

    report = migrate_ingest_artifacts_to_postgres(settings, user_id=args.user_id)
    print(json.dumps({"mode": "applied", **report.to_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

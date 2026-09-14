#!/usr/bin/env python3
"""Preview or explicitly purge legacy hierarchical vectors without tenant ownership."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.hierarchical_store import HierarchicalStore


CONFIRM_TOKEN = "PURGE_UNSCOPED_HIERARCHICAL_VECTORS"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview legacy capsule/section vectors that have no tenant metadata. "
            "These records cannot be safely auto-attributed; explicit purge is the "
            "supported cutover policy before regenerating vectors from tenant-owned data."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the previewed unscoped vectors. Without this flag the command is read-only.",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required with --apply. Must equal {CONFIRM_TOKEN}.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    store = HierarchicalStore()
    legacy = store.legacy_unscoped_vector_ids()
    counts = {key: len(ids) for key, ids in legacy.items()}

    if not args.apply:
        print(json.dumps({"mode": "preview", **counts}, sort_keys=True))
        return 0

    if args.confirm != CONFIRM_TOKEN:
        print(
            json.dumps(
                {
                    "mode": "blocked",
                    "reason": "explicit confirmation token required",
                    **counts,
                },
                sort_keys=True,
            )
        )
        return 2

    deleted = store.purge_legacy_unscoped_vectors(confirm=True)
    print(json.dumps({"mode": "applied", **deleted}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate migrated SQLite/Postgres lexical retrieval parity without writes."""

from __future__ import annotations

import argparse
import json

from app.db.fts_retrieval_parity import validate_lexical_retrieval_parity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-id",
        required=True,
        help="Exact tenant that owns the legacy SQLite source",
    )
    parser.add_argument(
        "--query",
        action="append",
        required=True,
        dest="queries",
        help="Representative lexical query; repeat for a query suite",
    )
    parser.add_argument("--limit", type=int, default=20)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = validate_lexical_retrieval_parity(
        args.queries,
        user_id=args.user_id,
        limit=args.limit,
    )
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

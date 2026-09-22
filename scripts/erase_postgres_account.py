"""Operator retry for an explicitly confirmed account after session revocation.

Run as: python -m scripts.erase_postgres_account --user-id ID --confirm-user-id ID
Uses the configured environment-owned database credentials; prints counts only.
"""
from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.services.privacy_erasure import erase_confirmed_account


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--confirm-user-id", required=True)
    args = parser.parse_args()
    result = erase_confirmed_account(get_settings(), user_id=args.user_id, confirm_user_id=args.confirm_user_id)
    # Error details may contain content; don't print them in operator reports.
    print(json.dumps({"deleted": result["deleted"], "account_fenced": result["account_fenced"],
                      "memory_deleted_count": result["memory_deleted_count"],
                      "memory_error_count": len(result["memory_errors"])}))
    if not result["deleted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Distinguish an unused optional domain from a failed privacy database read."""
from __future__ import annotations


def table_exists(conn, table: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) AS relation", (table,)).fetchone()
    return (row["relation"] if isinstance(row, dict) else row[0]) is not None

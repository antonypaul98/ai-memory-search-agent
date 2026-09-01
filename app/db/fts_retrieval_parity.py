"""Read-only lexical retrieval parity validation for P-03 cutover.

This gate compares the legacy SQLite FTS5 results with the tenant-scoped
Postgres lexical index after a migration. It never writes either store and it
never prints query text or indexed content. A migrated deployment should not
switch lexical production traffic until its representative query suite passes
this validator.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from app.config import Settings, get_settings
from app.db.postgres_fts_index import PostgresFTSIndex
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class LexicalParityMismatch:
    query_index: int
    sqlite_doc_ids: tuple[str, ...]
    postgres_doc_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LexicalParityReport:
    tenant: str
    queries_checked: int
    queries_matched: int
    mismatches: tuple[LexicalParityMismatch, ...]

    @property
    def passed(self) -> bool:
        return not self.mismatches

    def to_dict(self) -> dict[str, object]:
        return {
            "tenant": self.tenant,
            "queries_checked": self.queries_checked,
            "queries_matched": self.queries_matched,
            "mismatch_count": len(self.mismatches),
            "passed": self.passed,
            # Deliberately expose only result identities and query indexes; never
            # echo potentially private query text or indexed content.
            "mismatches": [mismatch.to_dict() for mismatch in self.mismatches],
        }


def validate_lexical_retrieval_parity(
    queries: Iterable[str],
    *,
    user_id: str,
    settings: Settings | None = None,
    connection_factory: ConnectionFactory | None = None,
    limit: int = 20,
) -> LexicalParityReport:
    """Compare deterministic ordered document identities for each supplied query.

    Exact ordered identity parity is intentional. Different backend score
    magnitudes remain hidden behind the stable public relevance-score contract,
    but a migration cutover must not silently change which documents are
    returned or their deterministic ordering for the operator's acceptance
    query suite.
    """
    tenant = _require_tenant(user_id)
    normalized_queries = tuple(query.strip() for query in queries if query.strip())
    if not normalized_queries:
        raise ValueError("at least one non-empty lexical parity query is required")

    bounded_limit = max(1, min(int(limit), 100))
    settings = settings or get_settings()
    factory = connection_factory or get_postgres_connection_factory(settings)
    postgres = PostgresFTSIndex(factory)

    mismatches: list[LexicalParityMismatch] = []
    with _open_source_read_only(settings) as sqlite_conn:
        for index, query in enumerate(normalized_queries, start=1):
            sqlite_ids = _sqlite_search_doc_ids(sqlite_conn, query, bounded_limit)
            postgres_ids = tuple(
                str(hit["doc_id"])
                for hit in postgres.search(query, user_id=tenant, limit=bounded_limit)
            )
            if sqlite_ids != postgres_ids:
                mismatches.append(
                    LexicalParityMismatch(
                        query_index=index,
                        sqlite_doc_ids=sqlite_ids,
                        postgres_doc_ids=postgres_ids,
                    )
                )

    return LexicalParityReport(
        tenant=tenant,
        queries_checked=len(normalized_queries),
        queries_matched=len(normalized_queries) - len(mismatches),
        mismatches=tuple(mismatches),
    )


def _sqlite_search_doc_ids(conn: sqlite3.Connection, query: str, limit: int) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT doc_id FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank, doc_id LIMIT ?",
        (query, limit),
    ).fetchall()
    return tuple(str(row["doc_id"]) for row in rows)


def _require_tenant(user_id: str) -> str:
    tenant = user_id.strip()
    if not tenant:
        raise ValueError("user_id is required for lexical retrieval parity validation")
    return tenant


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite parity source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn

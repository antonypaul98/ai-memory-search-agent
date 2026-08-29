from datetime import datetime, timezone

from app.db.postgres_job_claims import PostgresJobClaimStore


class Cursor:
    rowcount = 1

    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class Connection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        self.calls.append((sql, params))
        if "WITH candidate AS" in sql:
            return Cursor()
        return Cursor()


def test_claim_query_uses_postgres_boolean_predicate():
    conn = Connection()
    store = PostgresJobClaimStore(lambda: conn)

    assert store.claim_next_item(
        worker_id="worker-a",
        now=datetime(2026, 8, 29, tzinfo=timezone.utc),
    ) is None

    claim_sql = conn.calls[0][0]
    assert "bj.paused = FALSE" in claim_sql
    assert "bj.paused = 0" not in claim_sql

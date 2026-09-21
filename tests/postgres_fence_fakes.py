"""Unfenced schema responses for focused SQL-contract test doubles.

Real locking, durable marker and race behavior are covered with real Postgres in
 test_postgres_account_fence_acceptance.py, never by this helper.
"""
class UnfencedCursor:
    def fetchone(self):
        return None


def is_fence_query(statement):
    sql = " ".join(str(statement).split())
    return sql.startswith("SELECT pg_advisory_xact_lock_shared(730031,") or sql == (
        "SELECT 1 FROM pg_class WHERE oid = to_regclass('account_erasure_fences')"
    )

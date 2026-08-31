# P-03 Postgres cutover — auth/session slice

Status: **Partial P-03 milestone; not full Postgres production-profile completion.**

## Accepted in this slice

- Authentication/session persistence now has an explicit `sqlite | postgres` backend selector.
- SQLite remains the default so existing local and single-node deployments do not change behavior implicitly.
- Explicit Postgres selection uses the existing environment-indirected `DATABASE_URL` runtime and fails closed when the configured DSN is unavailable; it never silently falls back to SQLite.
- Postgres owns tenant user records and session lifecycle operations for this slice: local demo-user initialization, account creation/authentication, session create/resolve, and session revocation.
- Session ownership remains tied to the user record by a foreign key with cascading cleanup.
- Password hashing and session-token generation reuse the existing security primitives. DSNs, passwords, password hashes, and session tokens are not logged or copied into Memory metadata.
- The API auth dependency selects the configured persistence implementation without changing its external authentication contract.

## Regression boundary

`tests/test_postgres_auth_store.py` locks:

- safe SQLite default behavior;
- explicit Postgres selection and schema initialization;
- fail-closed behavior when an explicitly selected Postgres DSN is missing;
- users/sessions schema and tenant relationship;
- idempotent local-user initialization;
- active-session lookup only after exact-token expiry cleanup; and
- no database access for blank session tokens.

## Deliberately still incomplete

P-03 is **not complete** after this slice. The source-of-truth GAP-02 production profile still requires the remaining SQLite-backed relational surfaces to migrate, including the video/canonical registry, FTS/search-support state, caches and other applicable relational stores, plus migration/export/import tooling and a validated production profile that can retire SQLite safely.

The existing Postgres durable job store remains a separate previously implemented P-03 slice. This change does not claim that jobs + auth constitute the full production cutover.

## Memory and privacy invariants

This slice does not alter canonical Memory records, provenance/evidence, deterministic deduplication, confidence/trust calculations, vector collections, connector behavior, or AI routing. No mandatory LLM call is introduced. No Jarvis voice, vision, gesture, spatial, holographic, ambient-capture, or hardware behavior is introduced.

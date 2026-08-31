# P-03 Postgres video/reflection registry slice

Status: **Partial P-03 milestone**.

This slice moves the legacy tenant-scoped video save-intent, reflection, and usage registry onto the same explicit production persistence profile as canonical Memory records.

## Completed in this slice

- `MEMORY_STORE_BACKEND=sqlite` keeps the historical local SQLite registry unchanged.
- `MEMORY_STORE_BACKEND=postgres` routes video/reflection registry persistence to Postgres instead of silently writing local SQLite.
- Postgres selection reuses the environment-indirected DSN from `POSTGRES_DSN_ENV`; credentials are never written to repository configuration, cache keys, or Memory metadata.
- Postgres tables preserve deterministic `(user_id, video_id)` identity for both registry and reflection state.
- Save intent, reflection preferences, view/search counters, feedback counters, and tenant-aware duplicate checks preserve the existing registry contract.
- Explicit Postgres selection fails closed when the configured DSN environment variable is unavailable.
- Regression coverage verifies the backend boundary, tenant composite keys, cache reuse, and secret-free cache identity.

## Deliberately unchanged

- SQLite remains the safe local/self-host default.
- Canonical provenance, deterministic deduplication, confidence/evidence behavior, and confirmation gates are not weakened.
- No mandatory LLM or autonomous write path is introduced.
- No Jarvis voice, vision, gesture, spatial, holographic, ambient-capture, or hardware work is included.

## P-03 remains incomplete

Remaining work still includes SQLite FTS/search-support state, semantic/query caches and other remaining production relational state, safe/idempotent SQLite-to-Postgres migration tooling, real Postgres production-profile integration validation, and proof that the supported multi-worker production profile performs no SQLite writes before production SQLite retirement.

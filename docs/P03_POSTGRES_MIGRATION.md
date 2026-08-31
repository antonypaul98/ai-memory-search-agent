# P-03 — Production-wide Postgres migration

Status: **Partial**

P-03 is intentionally being completed in small, test-gated slices. SQLite remains the safe local/self-host default until the entire production profile and migration path are validated.

## Completed slices

- Durable job state / lease coordination can use Postgres.
- Auth and session persistence can explicitly use Postgres and fails closed when the environment-owned DSN is unavailable.
- Canonical universal memory records can explicitly use Postgres, including tenant identity, provenance, lifecycle events, version snapshots, trust snapshots/history, and deterministic tenant/source/external-id uniqueness.
- Postgres credentials remain environment-owned via `POSTGRES_DSN_ENV`; no DSN or secret is persisted in application metadata or cache keys.

## Current configuration

- `AUTH_STORE_BACKEND=sqlite|postgres`
- `MEMORY_STORE_BACKEND=sqlite|postgres`
- `JOB_STORE_BACKEND=sqlite|postgres`
- `POSTGRES_DSN_ENV=DATABASE_URL`

Selecting Postgres is fail-closed. The application must not silently fall back to SQLite when a production store was explicitly requested.

## Remaining before P-03 can be marked Complete

- Move the legacy video/reflection registry and applicable capture/bookmark relational state to the production Postgres profile.
- Move SQLite FTS/search-support state or replace it with the approved Postgres search equivalent while preserving deterministic retrieval behavior.
- Move semantic/query caches and any remaining production relational stores that still require SQLite.
- Add migration/export/import tooling that can transfer existing SQLite state safely and idempotently.
- Add production-profile integration validation against a real Postgres service, including rollback/failure behavior and tenant-isolation checks.
- Prove the supported multi-worker production profile no longer depends on SQLite writes before SQLite can be retired from that profile.

## Safety boundary

This milestone does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis voice/vision/gesture/spatial/holographic work.

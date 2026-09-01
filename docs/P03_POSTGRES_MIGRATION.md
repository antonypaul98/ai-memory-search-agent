# P-03 — Production-wide Postgres migration

Status: **Partial**

P-03 is intentionally being completed in small, test-gated slices. SQLite remains the safe local/self-host default until the entire production profile and migration path are validated.

## Completed slices

- Durable job state / lease coordination can use Postgres.
- Auth and session persistence can explicitly use Postgres and fails closed when the environment-owned DSN is unavailable.
- Canonical universal memory records can explicitly use Postgres, including tenant identity, provenance, lifecycle events, version snapshots, trust snapshots/history, and deterministic tenant/source/external-id uniqueness.
- The tenant-scoped video/reflection/usage registry follows the Postgres production profile while preserving composite `(user_id, video_id)` identity.
- A first SQLite -> Postgres migration tool covers the video/reflection registry. It previews by default, requires explicit `--apply` for target writes, opens SQLite read-only, migrates in deterministic tenant/video order, and never overwrites an existing Postgres row on retry.
- Capture request/status state can explicitly use Postgres while preserving tenant-scoped reads, retries and updates.
- Browser bookmark synchronization state can explicitly use Postgres, preserving tenant/browser identity, complete-snapshot removal semantics, and partial-snapshot safety.
- Import-run execution/history follows the Postgres bookmark production profile and keeps run/item reads, cancellation, updates, and history tenant-scoped.
- A tenant-scoped Postgres full-text index primitive exists with composite `(user_id, doc_id)` identity, explicit tenant filters on every query/mutation, GIN-backed search documents, and deterministic score/doc-id ordering.
- Lexical retrieval now has explicit `FTS_STORE_BACKEND=sqlite|postgres` selection and AHME forwards the resolved tenant identity to the selected index. The legacy SQLite FTS index remains available only for the unauthenticated local profile; authenticated SQLite lexical selection fails closed instead of risking an unscoped read.
- Postgres credentials remain environment-owned via `POSTGRES_DSN_ENV`; no DSN or secret is persisted in application metadata or cache keys.

## Current configuration

- `AUTH_STORE_BACKEND=sqlite|postgres`
- `MEMORY_STORE_BACKEND=sqlite|postgres`
- `CAPTURE_STORE_BACKEND=sqlite|postgres`
- `BOOKMARK_STORE_BACKEND=sqlite|postgres`
- `FTS_STORE_BACKEND=sqlite|postgres`
- `JOB_STORE_BACKEND=sqlite|postgres`
- `POSTGRES_DSN_ENV=DATABASE_URL`

Selecting Postgres is fail-closed. The application must not silently fall back to SQLite when a production store was explicitly requested. Authenticated lexical search additionally requires the tenant-scoped Postgres FTS backend because the historical SQLite FTS5 schema has no tenant column.

### Video/reflection migration

Preview counts without contacting Postgres:

```bash
python scripts/migrate_video_registry_to_postgres.py
```

Optionally scope the preview or migration to one exact tenant:

```bash
python scripts/migrate_video_registry_to_postgres.py --user-id <tenant-id>
```

Apply only after reviewing the preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_video_registry_to_postgres.py --apply
```

The command returns counts only; it does not print reflection text, URLs, credentials, or DSNs. Existing target rows are skipped rather than overwritten so a stale SQLite snapshot cannot clobber newer Postgres state.

## Remaining before P-03 can be marked Complete

- Finish the FTS/search-support cutover: route ingestion mutations through the selected tenant-aware lexical backend, migrate/backfill existing lexical documents safely, and validate deterministic retrieval parity before enabling Postgres FTS for a migrated deployment.
- Move semantic/query caches and any remaining production relational stores that still require SQLite.
- Extend migration/export/import tooling to the remaining SQLite-backed production state, including capture/bookmark/import-run and lexical state, with safe and idempotent transfer semantics.
- Add production-profile integration validation against a real Postgres service, including rollback/failure behavior and tenant-isolation checks.
- Prove the supported multi-worker production profile no longer depends on SQLite writes before SQLite can be retired from that profile.

## Safety boundary

This milestone does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis voice/vision/gesture/spatial/holographic work.

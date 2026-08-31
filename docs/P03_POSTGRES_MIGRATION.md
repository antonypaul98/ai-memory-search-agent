# P-03 — Production-wide Postgres migration

Status: **Partial**

P-03 is intentionally being completed in small, test-gated slices. SQLite remains the safe local/self-host default until the entire production profile and migration path are validated.

## Completed slices

- Durable job state / lease coordination can use Postgres.
- Auth and session persistence can explicitly use Postgres and fails closed when the environment-owned DSN is unavailable.
- Canonical universal memory records can explicitly use Postgres, including tenant identity, provenance, lifecycle events, version snapshots, trust snapshots/history, and deterministic tenant/source/external-id uniqueness.
- The tenant-scoped video/reflection/usage registry follows the Postgres production profile while preserving composite `(user_id, video_id)` identity.
- A first SQLite -> Postgres migration tool covers the video/reflection registry. It previews by default, requires explicit `--apply` for target writes, opens SQLite read-only, migrates in deterministic tenant/video order, and never overwrites an existing Postgres row on retry.
- Capture request/status state can explicitly use Postgres while preserving tenant-scoped reads, retries and updates. Bookmark/import-run state remains separate unfinished P-03 work.
- Postgres credentials remain environment-owned via `POSTGRES_DSN_ENV`; no DSN or secret is persisted in application metadata or cache keys.

## Current configuration

- `AUTH_STORE_BACKEND=sqlite|postgres`
- `MEMORY_STORE_BACKEND=sqlite|postgres`
- `CAPTURE_STORE_BACKEND=sqlite|postgres`
- `JOB_STORE_BACKEND=sqlite|postgres`
- `POSTGRES_DSN_ENV=DATABASE_URL`

Selecting Postgres is fail-closed. The application must not silently fall back to SQLite when a production store was explicitly requested.

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

- Move applicable bookmark/import-run relational state to the production Postgres profile.
- Move SQLite FTS/search-support state or replace it with the approved Postgres search equivalent while preserving deterministic retrieval behavior and tenant isolation.
- Move semantic/query caches and any remaining production relational stores that still require SQLite.
- Extend migration/export/import tooling to the remaining SQLite-backed production state, including capture state, with safe and idempotent transfer semantics.
- Add production-profile integration validation against a real Postgres service, including rollback/failure behavior and tenant-isolation checks.
- Prove the supported multi-worker production profile no longer depends on SQLite writes before SQLite can be retired from that profile.

## Safety boundary

This milestone does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis voice/vision/gesture/spatial/holographic work.

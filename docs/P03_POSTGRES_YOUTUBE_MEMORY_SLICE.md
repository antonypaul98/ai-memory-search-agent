# P-03 — Postgres YouTube memory and operational state

Status: **YouTube persistence/routing/migration complete; ingest-artifact primitive and selector implemented, runtime routing pending validation**

The production-wide Postgres audit found that `YouTubeMemoryStore` still persisted connector-specific memory and ingest state through the legacy SQLite schema. The Postgres primitive now covers both core durable YouTube memory records and the operational state that must move with them before any runtime cutover.

## Covered

- `youtube_memories` Postgres schema with deterministic composite `(user_id, video_id)` uniqueness.
- Tenant-prefixed content-hash and saved-time indexes.
- Core upsert, exact lookup, content-hash duplicate lookup, and per-user listing.
- Tenant-scoped pipeline-stage history using `(user_id, run_id)` read identity.
- Tenant-scoped retry/dead-letter state with deterministic `(next_attempt_at, id)` due ordering and `(user_id, connector_id, external_id)` uniqueness.
- Per-tenant connector metrics and diagnostics; metrics cannot aggregate one user's state into another user's counters.
- Every Postgres operational read and mutation includes tenant identity rather than copying the legacy unscoped SQLite diagnostic/retry behavior forward.
- Explicit `youtube_store_backend=sqlite|postgres` configuration and one fail-closed selector for the complete YouTube memory/operational store boundary.
- The selector's SQLite implementation accepts tenant-explicit selected-store calls. Legacy SQLite metrics remain local/global while retry claiming and successful retry completion are tenant-scoped; Postgres remains the tenant-isolated production target.
- `YouTubeRelatedService`, `IngestService`, the YouTube API, and `YouTubeDuplicateDetector` obtain their default store through the shared selector while preserving explicit injection where needed.
- Ingestion supplies `user_id` to operational metric mutations; pipeline/retry operations are tenant-explicit.
- Successful retry completion is backend-neutral and scoped by tenant, retry id, and connector; the API no longer deletes retry rows directly through SQLite.
- The runtime constructor audit found no additional YouTube connector store construction in the source connector; network retrieval remains persistence-neutral.
- SQLite remains the local/self-host default. Selecting Postgres requires environment-owned Postgres configuration and cannot silently fall back to SQLite when the DSN is missing.
- Postgres credentials remain environment-owned through the shared Postgres connection factory; no DSN or secret is persisted.
- Preview-first, source-read-only SQLite → Postgres migration is merged for YouTube memories, pipeline history, retry/dead-letter state, and connector metrics.

## YouTube state migration

`scripts/migrate_youtube_state_to_postgres.py` and its migration primitive cover the complete YouTube persistence boundary:

- preview is the default; target writes require explicit `--apply`;
- the SQLite source is opened read-only and all source state is captured from one snapshot before target writes;
- core memories use `(user_id, video_id)` conflict protection and never overwrite existing Postgres rows;
- retry/dead-letter state uses `(user_id, connector_id, external_id)` conflict protection and preserves existing target state;
- pipeline telemetry is copied in deterministic tenant/run/source-id order and uses a deterministic migration ledger so retries do not duplicate history while distinct legacy rows remain distinct;
- output is count/boolean only and never exposes URLs, payloads, errors, metadata, DSNs, or credentials;
- optional `--user-id` filtering is exact and blank tenant identity fails closed.

### Legacy metric attribution safety

Legacy SQLite `connector_metrics` are global and have no `user_id`, while the Postgres target is tenant-scoped. The migration therefore refuses **all target writes** when legacy YouTube metrics exist but the source contains zero or multiple identifiable tenants, or when `--user-id` does not match the sole identifiable tenant. It never guesses ownership or duplicates global counters across tenants. A single-tenant source can safely map those legacy metrics to that one tenant; existing Postgres metric rows remain authoritative and are not overwritten.

Preview:

```bash
python scripts/migrate_youtube_state_to_postgres.py
```

Optional exact-tenant preview:

```bash
python scripts/migrate_youtube_state_to_postgres.py --user-id <tenant-id>
```

Apply only after reviewing the preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_youtube_state_to_postgres.py --apply
```

## Remaining ingest-artifact relational state

The remaining direct relational SQLite ingestion helpers are transcript hashes and serialized capsule JSON. The tenant-scoped Postgres primitive is merged and the selector slice now establishes one backend boundary for both artifacts:

- `ingest_artifacts` uses `(user_id, video_id)` as its primary identity;
- transcript unchanged checks require tenant + video identity;
- transcript-hash upserts update only the hash and never erase an existing capsule;
- capsule-JSON upserts update only the capsule and never erase an existing transcript hash;
- blank tenant/video identity or blank persisted payloads fail closed before writes;
- `get_ingest_artifact_store()` deliberately reuses `youtube_store_backend` instead of introducing an independent switch, so production cannot select Postgres for YouTube memory while silently retaining SQLite artifact writes;
- Postgres selection resolves the environment-owned DSN through the shared fail-closed runtime and never falls back to SQLite;
- the SQLite adapter preserves the historical local/self-host tables behind the same tenant-explicit method signatures while Postgres remains the tenant-isolated production target.

Runtime call sites in `IngestService` / `store_capsule_json` are intentionally not changed in this selector prerequisite. After exact-head validation, the next slice routes transcript unchanged checks, transcript hash writes, and capsule JSON writes through the selector with explicit `user_id`, then provides preview-first migration for legacy `content_hashes` and `memory_capsules_json` rows. Because the legacy tables are keyed only by `video_id`, tenant ownership must be proven from canonical tenant-bearing records rather than guessed.

Production acceptance also still requires real-Postgres integration/rollback/tenant-isolation validation and proof that the supported multi-worker production profile performs no SQLite writes.

## Next acceptance slice

After the selector validates, route every ingest-artifact call site through it with tenant identity. Then add safe legacy artifact migration and continue through the real-Postgres and zero-SQLite-write acceptance gates.

This work does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis-specific voice/vision/gesture/spatial/holographic work.

# P-03 — Postgres YouTube memory and operational state

Status: **Persistence primitive complete; runtime routing not yet enabled**

The production-wide Postgres audit found that `YouTubeMemoryStore` still persists connector-specific memory and ingest state through the legacy SQLite schema. The Postgres primitive now covers both core durable YouTube memory records and the operational state that must move with them before any runtime cutover.

## Covered

- `youtube_memories` Postgres schema with deterministic composite `(user_id, video_id)` uniqueness.
- Tenant-prefixed content-hash and saved-time indexes.
- Core upsert, exact lookup, content-hash duplicate lookup, and per-user listing.
- Tenant-scoped pipeline-stage history using `(user_id, run_id)` read identity.
- Tenant-scoped retry/dead-letter state with deterministic `(next_attempt_at, id)` due ordering and `(user_id, connector_id, external_id)` uniqueness.
- Per-tenant connector metrics and diagnostics; metrics cannot aggregate one user's state into another user's counters.
- Every operational read and mutation includes tenant identity rather than copying the legacy unscoped SQLite diagnostic/retry behavior forward.
- Existing SQLite behavior remains the local/self-host default; no runtime routing changes occur in this slice.
- Postgres credentials remain environment-owned through the shared Postgres connection factory; no DSN or secret is persisted.

## Deliberately not yet routed

The runtime must not switch only part of `YouTubeMemoryStore`. Core memory rows, pipeline telemetry, retry/dead-letter state, and metrics/diagnostics need one fail-closed backend selection so a claimed Postgres production profile cannot silently continue writing SQLite.

The audit also identified separate direct SQLite ingestion helpers for transcript hashes and serialized capsule JSON. Those remain P-03 work and must not be treated as migrated by this slice.

## Next acceptance slice

Add explicit fail-closed YouTube-store backend selection and route the complete YouTube memory/operational boundary together. Then add safe, idempotent SQLite-to-Postgres migration tooling before enabling the Postgres profile for existing deployments. After that, continue the audit for transcript-hash/capsule-JSON state and the remaining real-Postgres/zero-SQLite-write acceptance gates.

This work does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis-specific voice/vision/gesture/spatial/holographic work.

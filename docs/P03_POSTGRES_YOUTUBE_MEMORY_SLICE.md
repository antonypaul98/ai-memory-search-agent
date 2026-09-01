# P-03 — Postgres YouTube memory and operational state

Status: **Persistence primitive, selector, and runtime constructor routing complete; migration next**

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
- `YouTubeRelatedService` obtains its YouTube memory store through the explicit selector while preserving explicit store injection for tests/callers.
- `IngestService` obtains the complete YouTube persistence boundary through `get_youtube_memory_store()` and supplies `user_id` to every operational metric mutation, while its existing pipeline/retry mutations remain tenant-explicit.
- The YouTube API dependency obtains the selected store rather than directly constructing SQLite. Diagnostics and retry processing pass tenant identity explicitly.
- Successful retry completion is a backend-neutral selected-store operation scoped by tenant, retry id, and connector; the API no longer deletes retry rows directly through the SQLite schema.
- `YouTubeDuplicateDetector` obtains its default store through the same selector, while preserving explicit store injection. Duplicate checks therefore cannot silently bypass Postgres selection by constructing the legacy SQLite store.
- The runtime constructor audit found no additional YouTube connector store construction in the source connector; network retrieval remains persistence-neutral.
- SQLite remains the local/self-host default. Selecting Postgres requires environment-owned Postgres configuration and cannot silently fall back to SQLite when the DSN is missing.
- Postgres credentials remain environment-owned through the shared Postgres connection factory; no DSN or secret is persisted.

## Remaining YouTube P-03 work

Safe idempotent SQLite-to-Postgres migration tooling is still required for existing YouTube memory and operational state before enabling the Postgres profile for an existing deployment. The complete boundary must stay unified: core memory rows, pipeline telemetry, retry/dead-letter state, and metrics/diagnostics cannot silently split between Postgres and SQLite.

The audit also identified separate direct SQLite ingestion helpers for transcript hashes and serialized capsule JSON. Those remain P-03 work and must not be treated as migrated by this slice.

## Next acceptance slice

Add preview-first, source-read-only, tenant-safe SQLite-to-Postgres migration tooling for YouTube memory and operational state with deterministic ordering and idempotent target protection. After that, continue the audit for transcript-hash/capsule-JSON state and the remaining real-Postgres/zero-SQLite-write acceptance gates.

This work does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis-specific voice/vision/gesture/spatial/holographic work.

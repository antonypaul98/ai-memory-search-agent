# P-03 — Postgres YouTube memory and operational state

Status: **Persistence primitive and selector complete; runtime call-site routing in progress**

The production-wide Postgres audit found that `YouTubeMemoryStore` still persists connector-specific memory and ingest state through the legacy SQLite schema. The Postgres primitive now covers both core durable YouTube memory records and the operational state that must move with them before any runtime cutover.

## Covered

- `youtube_memories` Postgres schema with deterministic composite `(user_id, video_id)` uniqueness.
- Tenant-prefixed content-hash and saved-time indexes.
- Core upsert, exact lookup, content-hash duplicate lookup, and per-user listing.
- Tenant-scoped pipeline-stage history using `(user_id, run_id)` read identity.
- Tenant-scoped retry/dead-letter state with deterministic `(next_attempt_at, id)` due ordering and `(user_id, connector_id, external_id)` uniqueness.
- Per-tenant connector metrics and diagnostics; metrics cannot aggregate one user's state into another user's counters.
- Every Postgres operational read and mutation includes tenant identity rather than copying the legacy unscoped SQLite diagnostic/retry behavior forward.
- Explicit `youtube_store_backend=sqlite|postgres` configuration and one fail-closed selector for the complete YouTube memory/operational store boundary.
- The selector's SQLite implementation accepts tenant-explicit metric calls, allowing runtime services to preserve tenant identity without backend-specific branching; legacy SQLite metrics remain local/global and Postgres remains the tenant-isolated production target.
- `YouTubeRelatedService` now obtains its YouTube memory store through the explicit selector while preserving explicit store injection for tests/callers.
- SQLite remains the local/self-host default. Selecting Postgres requires environment-owned Postgres configuration and cannot silently fall back to SQLite when the DSN is missing.
- Postgres credentials remain environment-owned through the shared Postgres connection factory; no DSN or secret is persisted.

## Runtime routing still required

`IngestService`, the YouTube API dependency, and any other remaining direct `YouTubeMemoryStore` constructors still need to be routed through `get_youtube_memory_store()`. That routing must not switch only part of the store: core memory rows, pipeline telemetry, retry/dead-letter state, and metrics/diagnostics must move together so a claimed Postgres profile cannot silently continue writing SQLite.

The retry-processing endpoint currently completes successful retries by deleting directly from the legacy SQLite queue. Before that endpoint can use the selected backend, retry completion needs a backend-neutral, tenant-scoped store operation. The legacy SQLite operational schema also predates the tenant-scoped Postgres contract: pipeline reads, due-retry claiming, and connector metrics/diagnostics contain unscoped behavior. Runtime routing must preserve the stricter tenant-explicit contract rather than weakening Postgres to match those legacy signatures.

The audit also identified separate direct SQLite ingestion helpers for transcript hashes and serialized capsule JSON. Those remain P-03 work and must not be treated as migrated by this slice.

## Next acceptance slice

Route `IngestService` through the selector and pass tenant identity to every operational metric call, now that both selected backends accept that caller contract. Then add the backend-neutral tenant-scoped retry completion needed to route the YouTube API dependency safely, finish remaining direct constructors, and add safe idempotent SQLite-to-Postgres migration tooling before enabling the Postgres profile for existing deployments. After that, continue the audit for transcript-hash/capsule-JSON state and the remaining real-Postgres/zero-SQLite-write acceptance gates.

This work does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis-specific voice/vision/gesture/spatial/holographic work.

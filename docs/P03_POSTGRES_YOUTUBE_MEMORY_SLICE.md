# P-03 — Postgres YouTube memory primitive

Status: **Primitive implemented; runtime routing not yet enabled**

The production-wide Postgres audit found that `YouTubeMemoryStore` still persists connector-specific memory and ingest state through the legacy SQLite schema. This slice moves only the core durable YouTube memory/duplicate metadata boundary into a tenant-scoped Postgres primitive before any runtime cutover.

## Covered in this slice

- `youtube_memories` Postgres schema with deterministic composite `(user_id, video_id)` uniqueness.
- Tenant-prefixed content-hash and saved-time indexes.
- Core upsert, exact lookup, content-hash duplicate lookup, and per-user listing.
- Every read identity is explicitly tenant-scoped.
- Existing SQLite behavior remains the local/self-host default; no runtime routing changes occur in this slice.
- Postgres credentials remain environment-owned through the shared Postgres connection factory; no DSN or secret is persisted.

## Deliberately not yet routed

`YouTubeMemoryStore` also owns pipeline-stage telemetry, connector retry/dead-letter state, and connector metrics. Those surfaces must be designed with explicit tenant boundaries before the production backend is switched. Routing only the core memory rows now would create a hidden split where ingestion still writes SQLite, so this PR adds the primitive without enabling it.

The audit also identified separate direct SQLite ingestion helpers for transcript hashes and serialized capsule JSON. Those remain P-03 work and must not be treated as migrated by this slice.

## Next acceptance slice

Complete tenant-safe Postgres persistence for the remaining YouTube pipeline/retry/diagnostic state, then add fail-closed backend selection and route all YouTube ingest state together. Add safe migration tooling before enabling the Postgres profile for existing SQLite deployments.

This work does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis-specific voice/vision/gesture/spatial/holographic work.

# P-03 Final Acceptance Evidence

Updated: 2026-09-14

Status: **Partial — implementation defects confirmed during exact-head review; deployment-specific cutover remains unexecuted.**

This document is a narrow current handoff for the final P-03 production-wide Postgres migration acceptance pass. It does not replace `P03_POSTGRES_MIGRATION.md` or `P03_SQLITE_RUNTIME_AUDIT.md`; it records newer validated evidence that supersedes stale next-work statements in those files until their final reconciliation.

## Current verified main

Main through PR #282 includes the validated P-03 runtime and readiness work described below. Preserve these changes; do not rebuild them from older audit tables.

## Hierarchical vector ownership and privacy — validated slices, incomplete boundary

The hierarchical capsule/section boundary identified by the earlier runtime audit has now been repaired in bounded slices:

- PR #276 tenant-scopes hierarchical vector IDs, metadata, retrieval, and deletion.
- PR #277 forwards the exact ingest owner to hierarchical delete/capsule/section writes.
- PR #278 defines the legacy unscoped-vector cutover policy: ownership is never guessed; preview is non-destructive; purge requires explicit apply/confirmation and only targets unowned legacy vectors.
- PR #281 hardens legacy inventory so missing metadata cannot disappear through truncated ID/metadata pairing.
- PR #280 makes privacy deletion remove the deleting tenant's hierarchical vectors even for a shared external source, preserves neighboring tenants, and propagates vector-deletion failure before canonical ownership is removed so retry remains safe. Exact-head CI #1093 passed; merged as `0c115fc6ea9989cb34bd85024452aa5069d040f5`.

These slices do not yet close the full hierarchical boundary. Review of main
`c3ffdd8456036e8cfb5eb9f817e5bb7b2994dc4d` confirmed:
- the real `HierarchicalStore.delete_video` catches and discards deletion errors;
  #280's helper test injects an error above that swallowing layer;
- unscoped deletion matches every owner for an external ID, rather than only
  legacy vectors; registry exclusivity is not proof of vector ownership;
- #277 scopes YouTube IngestService, but generic ConnectorIngestService still
  calls hierarchical delete/capsule/section writes without a tenant.

PR #284 repairs the actual deletion boundary and tests real Chroma plus Postgres
privacy retryability. PR #285 scopes generic connector writes and adds actual
PDF ingest/canonical finalization/hierarchical retrieval/failure-retry acceptance.
Inspect each exact-head CI before accepting those repairs. Existing implementation
is preserved; these are remaining caller/boundary defects, not a restart.

No operator has purged legacy vectors from a live deployment in this session.

## Production dependency readiness — validated

PR #282 keeps `/live` dependency-free and makes `/ready` plus the backward-compatible `/health` alias verify the selected relational backend when the complete Postgres production profile is active.

The Postgres probe:

- reuses the existing environment-owned connection factory;
- performs a read-only `SELECT 1`;
- performs no schema writes;
- does not add a dependency;
- returns a generic unavailable response without exposing DSNs, credentials, hosts, or driver details;
- preserves the historical Chroma-only behavior for local/self-host profiles.

Exact-head CI #1095 passed; merged as `c3ffdd8456036e8cfb5eb9f817e5bb7b2994dc4d`.

## Existing real-Postgres acceptance that must not be rebuilt

The following executable evidence already exists and should be reused for final P-03 accounting:

1. `tests/test_postgres_fts_retrieval_parity_e2e.py` runs the lexical parity validator against a real Postgres service, proves an exact ordered-document parity success, proves cross-tenant rows cannot contaminate the selected tenant, and proves a mismatch keeps the gate closed. Reports omit query text.
2. `tests/test_postgres_production_lifespan.py` runs the complete Postgres profile in an isolated real schema with two live polling workers; exercises auth/session state, tenant-scoped lexical retrieval, privacy export/delete, review schedules and EventBus operations; injects lifespan failure; proves worker shutdown; rejects every Python relational `sqlite3.connect` attempt; and verifies no forbidden SQLite database is created.
3. Earlier #252–#258 acceptance covers migrated lexical parity plus worker/ingest success, failure, retry, and multi-worker claim exclusivity on real Postgres.
4. #271/#272 plus #280 cover read/export and destructive privacy boundaries, including shared-source tenant isolation and retry-safe deletion failure.

These tests are service-container acceptance. They are not evidence that a live production tenant has already been migrated.

## Remaining P-03 closure boundary

Implementation acceptance remains open independently of deployment:
- Validate and merge #284/#285, then rerun the combined main acceptance.
- Reconcile canonical embedding references with tenant-scoped vector IDs:
  UniversalMemoryService still constructs source-only capsule/section/evidence
  references while the corresponding repositories write tenant-scoped IDs.
- Finish the operational privacy/export/retention inventory and remaining
  production-profile caller acceptance. Bounded green fixtures do not certify
  unexecuted paths.
- Legacy inventory currently suppresses backend read errors; a failed inventory
  must not be mistaken for a verified empty cutover preview.

Separately, operator/deployment prerequisites are:

- Run the preview-first migration/cutover sequence against the actual deployment's legacy source and Postgres target, if such a deployment exists.
- Run the lexical parity validator with that deployment's representative query suite and exact tenant identity before enabling Postgres FTS for migrated traffic.
- Confirm rollback/failure procedure and environment-specific readiness in that deployment.
- Do not expose credentials or private query/content data in reports.

This deployment step cannot be fabricated from CI. It requires the real deployment environment, its environment-owned Postgres DSN, the exact tenant/operator selection, and an approved maintenance/cutover window if live data is present.

If there is no live legacy production deployment to migrate, final P-03 reconciliation should explicitly classify this as an operator/deployment prerequisite rather than inventing a production migration that never occurred.

## Gate accounting

**Jarvis Gate: 22/29 cleared — 7 remaining (historical continuity baseline).**

Do not advance the historical top-level count merely because these bounded P-03 slices merged. P-03 remains Partial until its final implementation-vs-deployment accounting is reconciled in the canonical source-of-truth documents and all remaining planned Memory Search acceptance/stability items are validated.

No Jarvis-specific voice, vision, gesture, spatial, holographic, or ambient physical-interface work is authorized by this evidence document.

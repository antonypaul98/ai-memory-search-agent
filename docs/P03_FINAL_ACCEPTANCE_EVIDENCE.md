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

## Validated generic connector follow-up

PR #285 exact head `85a3d5f3f86ac062fb9d9c2ee48866b5cefbe0ec` passed
[CI #1099](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/34873132249)
with 1,168 Python tests, extension checks and benchmark; merged as
`c971a07902c8e0ea3a093bd86dea28e20f9b4d70`. Its offline PDF acceptance runs actual
canonical/lifecycle/trust/graph finalization, tenant-scoped hierarchical retrieval,
and section-write failure/retry against Postgres and Chroma, with only embeddings
substituted and relational SQLite connections rejected. This supersedes the
pending generic-connector item above. #284 subsequently passed independently.

## Validated actual deletion follow-up

PR #284 exact head `8f7cf3bbc8f9fface20da704c6249eaa03db5848` passed
[CI #1098](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/34872976874)
with 1,172 Python tests, extension checks and benchmark; merged as
`3cd303ec922bf066d1fa6efaee2fb0d9c3020296`. Actual Chroma deletion failures now
propagate as sanitized errors; real Postgres ownership survives either collection's
injected failure and retry succeeds. Legacy-only deletion preserves known vector
owners regardless of the caller's registry-exclusivity view. These results
supersede the pending #284/#285 statements in the chronological review above.

**Next implementation checkpoint:** canonical embedding-reference integrity.
Verify the canonical capsule, section and evidence IDs resolve to records owned by
the same tenant. Then address fail-closed legacy inventory and finish operational
privacy/final production acceptance. P-03 stays Partial; gate count unchanged.

## Model usage privacy integration — 2026-09-15

#295 merged as `4f4ed118749447af730b19b1cd211e6366b3f5f5` after CI #1125.
The follow-up wires its exact-tenant primitives through the initialized Postgres
ledger into JSON/Markdown export and production erasure. The existing combined
production acceptance now checks empty-account export, two tenants' usage rows,
logical erasure, neighbor preservation, and a database-triggered failure/retry
while two workers poll and Python relational SQLite access is rejected. CI on
the follow-up head passed: #296 head `7070f50864035cec24a4e131c44171506c057796`,
CI #1127 / run 34912421871, 1,191 Python tests, 27 extension tests and benchmark.
Merged as `8e1cc8ab59ab59c6f2bff153829f75c04c26ab3f`.

A failed usage deletion propagates; earlier memory/feedback deletions may already
be committed. Retrying the same tenant completes the remaining domain. This is
idempotent multi-domain progress, not a transaction spanning all domains and not
a guarantee against concurrent writes. Remaining operational stores and account
revocation are still open P-03 requirements.

Logical SQL deletion is distinct from physical storage reclamation. PostgreSQL
retains old row versions for MVCC; VACUUM reclaims reusable space, and does not
establish backup erasure. See [PostgreSQL 16 routine vacuuming](https://www.postgresql.org/docs/16/routine-vacuuming.html).
Backup/WAL retention, replicas and operator-controlled physical purge require
separate deployment policy and evidence. No infrastructure purge was performed.

## Current remaining boundary — 2026-09-15

The [operational privacy inventory](P03_OPERATIONAL_PRIVACY_INVENTORY.md) is the
current table-level continuation reference. It supersedes pending references to
merged #286/#287 and feedback/usage slices above. All 52 literal PostgreSQL table
declarations are classified, with implementation gaps distinguished from operator
retention requirements. P-03 remains Partial: limited export enumeration,
operational/graph residual data and account/write-fencing semantics are not closed
by #296. Next: EventBus safe export and exact-tenant deletion/rollback acceptance.

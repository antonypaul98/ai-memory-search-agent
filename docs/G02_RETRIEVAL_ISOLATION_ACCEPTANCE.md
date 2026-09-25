# G02 / F-09–10 retrieval and search isolation acceptance

Updated: 2026-09-25. Status: **Accepted — implementation and exact-head CI passed in #382**.

## Existing acceptance contract and gate decision

The existing G02 row in `JARVIS_GATE_LEDGER.md` requires hierarchical and flat
search to preserve tenant evidence and metadata. It was still Partial on main
`cd3d2e61690dbf53943eb49fe938897ce74d4c7c`, even though P-03/G26 and U-03/G27
had separate accepted closeouts. G28 was already Complete; G29 explicitly retained
historical mapping and all-version reconciliation work.

Simply correcting P-03/U-03 labels would only reconcile the existing 24/29 state.
G02 is the single additional acceptance addressed by #382. It does not count
P-03, Daily Briefing or release packaging twice, redefine G29, or authorize
checkpoint 26. The running count is historical continuity, not a sum of candidate
G-rows or a claim to have recovered their missing original mapping.

## Reproduced implementation gap and repair

The original capsule, section and evidence IDs joined unescaped tenant/source
components with underscores. `(tenant="a_b", source="c")` and
`(tenant="a", source="b_c")` produced identical IDs; upserting one overwrote the
other despite correct query-time ownership filters. The new real-Chroma
regression fails on unchanged starting main with one capsule where two are
required. Filtering cannot recover a neighbor's overwritten vector.

`app/db/vector_identity.py` hashes a canonical JSON tuple of level/source type,
exact tenant, external identity and optional index into a versioned namespace.
`HierarchicalStore`, `MemoryRepository` and `UniversalMemoryService` use this one
function for writes and canonical references. Tenant predicates, provenance,
confidence, confirmation gates and account-erasure locks are preserved. There
is no new AI call, dependency, backend or broad refactor.

Existing persisted IDs and canonical references remain readable and are not
rewritten. Normal force-refresh ingestion deletes/replaces only the exact tenant's
source vectors and records the new references. This repair prevents future
collisions; it does not reconstruct content already overwritten in an unknown
live deployment. Operators can re-ingest an affected known source if necessary;
no live migration or recovery has been fabricated.

## Acceptance matrix

| Requirement | Executable evidence |
| --- | --- |
| Flat retrieval excludes neighbors and unrelated tenants; metadata/usage belong to the requested owner | `test_postgres_search_service_acceptance.py::test_real_search_service_postgres_tenants_and_telemetry[flat]` — real selected PostgreSQL stores, Chroma and SearchService |
| Hierarchical capsule/section/evidence retrieval retains owner and source metadata | Same test `[hierarchical]`; `test_postgres_connector_hierarchy_acceptance.py` performs actual PDF ingestion and AHME retrieval for two tenants sharing a source |
| Hierarchy failure does not bypass tenant filtering | Same SearchService test `[flat_fallback]` injects hierarchy failure and verifies actual flat fallback, owned result text, neighbor isolation and telemetry |
| Distinct tenant/source tuples cannot overwrite each other | `test_vector_identity_acceptance.py::test_ambiguous_components_cannot_overwrite_neighbor_and_refs_resolve` — real Chroma capsule/section/evidence writes with the colliding old identities |
| Canonical evidence references resolve; replay remains deterministic | The same test writes each source twice, verifies exact vector counts and resolves all canonical embedding references to stored tenant/source metadata |
| Exact-tenant deletion preserves the neighbor | Same regression deletes one tenant's source and still retrieves the other's evidence and sections |
| Older owned vector IDs remain readable without widening visibility | `test_vector_identity_acceptance.py::test_preexisting_owned_vector_ids_remain_readable` |
| Production retrieval does not open application relational SQLite | SearchService and generic connector acceptance reject every Python `sqlite3.connect` attempt. Native Chroma persistence is a separate vector boundary |

## Validation record

- Starting main passed CI #1349 / [run 36016762611](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/36016762611).
- The new regression run on unchanged starting main: **1 failed, 1 passed**;
  failure is the reproduced cross-tenant overwrite, not a mocked database failure.
- Focused local suite after repair: **16 passed, 3 skipped** (PostgreSQL service
  cases run in CI). This includes canonical reference and Daily Briefing regressions.
- Full local run: **1,282 passed, 75 skipped, 2 environment failures**: public DNS
  resolution and model-client SOCKS dependency. Neither test is disabled in CI.
- Exact-head CI for implementation commit `c8b2675462d32ed81aba942dbfeb08d6385326c9`:
  **passed CI #1350**, [run 36178736364](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/36178736364):
  **1,358 passed, 1 skipped**, all 27 extension tests, version/manifest agreement
  and AHME benchmark smoke. PostgreSQL service-container acceptance executed.

**Jarvis Gate: 25/29 cleared — 4 remaining.** This promotion rests on the
reproduced defect, implemented fix and successful full CI, not documentation alone.
The final documentation head must also pass required CI before merge.

Required PR CI runs the full
suite with PostgreSQL 16 and Redis 7, extension helpers, version/manifest agreement
and benchmark smoke. Promotion and merge require those checks to pass.

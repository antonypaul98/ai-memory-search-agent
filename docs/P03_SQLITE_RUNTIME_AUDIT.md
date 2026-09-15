# P-03 current runtime audit

## Current audit — 2026-09-15

P-03 remains **Partial**. #296 merged model-usage privacy integration after
CI #1127 / run 34912421871 passed (1,191 Python tests, 27 extension tests,
benchmark); main merge `8e1cc8ab59ab59c6f2bff153829f75c04c26ab3f`.
The [52-table operational privacy inventory](P03_OPERATIONAL_PRIVACY_INVENTORY.md)
is the current continuation reference. Missing complete export enumeration,
operational/graph erasure and account/write-fencing integration are implementation
gaps, not merely deployment prerequisites. Older pending PR references below are
historical. Next: EventBus safe export and tenant deletion with rollback tests.
No live migration or physical/backup purge is claimed; those require separate
operator evidence. Chroma native storage remains outside the relational SQLite
sentinel boundary. Gate continuity stays 22/29; no top-level checkpoint advanced.


## Current authority — review after #282

Verified main `c3ffdd8456036e8cfb5eb9f817e5bb7b2994dc4d`.
[P03 final acceptance evidence](P03_FINAL_ACCEPTANCE_EVIDENCE.md) supersedes
the older current/next-work table below. #273–#282 are merged, including
tenant-scoped hierarchy APIs, YouTube ingest propagation, legacy purge tooling,
privacy helper changes and production Postgres readiness.

P-03 is still Partial: #284 addresses swallowed real vector deletion failures and
overbroad legacy cleanup; #285 addresses omitted tenant IDs in generic connector
hierarchy writes. Further acceptance must reconcile canonical vector-reference
identities, fail-closed legacy inventory and operational privacy coverage.
No full-runtime or live-production certification is inferred from green mocks.

## Prior audit snapshot (superseded where noted above)

Updated 2026-09-14; verified main `d4cb7a2bd2060981dc5fe5da2f5d3e767c711b0b`
(PR #272). **P-03 remains Partial.** The historical inventory below is retained
for traceability; this current table supersedes its next-work instructions.

| Runtime surface | Current evidence and remaining boundary |
| --- | --- |
| Startup / IngestService migration | Complete-profile gates merged #243/#245; #257/#258 exercise real ingest orchestration with external/vector dependencies isolated. PR #273 adds actual lifespan/live polling worker acceptance and shutdown-on-exception repair; CI must validate its exact head. |
| SearchService | Fresh audit found direct legacy YouTubeMemoryStore construction. PR #274 routes through the selected store and forwards tenant identity to telemetry. Its first CI also caught the legacy canonical get_memory_store helper returning SQLite; the follow-up delegates explicit Postgres to the existing factory for all legacy callers. Actual flat AHME/Chroma search is tested with deterministic external embeddings; exact-head CI remains required. |
| HierarchicalStore / AHME | Capsules and sections currently have source-only vector IDs, no tenant metadata/query filter; AHME calls search_level without owner. This is a concrete isolation gap. Add tenant-scoped writes/search/delete and legacy ownership policy before claiming full search/privacy acceptance. It is outside relational SQLite accounting but inside the Memory transition gate. |
| Auth/canonical/registry/capture/bookmarks/imports/jobs/YouTube/FTS/cache/artifacts/content URL index | Existing selected factories and migrations remain authoritative. Do not rebuild from the old table. Real-Postgres bounded tests include #247, #249, #252–258. Whole-profile production/operator acceptance remains open. |
| Graph and intelligence | Selected graph/topic/edge/capsule/creator/event stores already exist; #248 covers graph runtime. Historical direct-SQLite claims below are obsolete. |
| Review schedules | #259 runtime atomic updates/concurrency, #260 privacy, #261 read-only ownership-validated migration. #261 exact-head CI 34804091352 passed; merge 79a032a. Live legacy deployment transfer not executed. |
| EventBus / OAuth / agents / status | #262/#263/#264/#265/#266 route EventBus, encrypted tokens, runtime state, ingest rules/claims and search activity to Postgres through memory_store_backend. Local branches remain intentional. |
| Model usage / feedback | #267/#269/#270 supply Postgres ledger and runtime routing when the complete production profile is selected. Mixed/local profiles retain their documented SQLite behavior. Audit new records against privacy retention/export requirements. |
| PrivacyService | #271 export and #272 deletion execute real selected stores and Chroma with relational sqlite3.connect rejected. #272 CI 34836155411 is green. These fixtures do not certify every derived/operational data family; export/delete inventory and hierarchical vector ownership remain open. |
| Explicit local SQLite adapters | sqlite_client has no application consumer in the inspected tree; its tests use it as an explicit local adapter. Local store classes, schema helpers and read-only migration sources are not by themselves production bypasses. |
| Health/readiness | HealthService probes Chroma only. Validate selected relational dependency readiness before production acceptance; process liveness must remain independent. |

## Current next work

1. Finish exact-head validation/merge of #273 and #274; fix failures first.
2. Repair hierarchical vector tenant identity across every write/read/delete caller,
   with two-tenant shared-source regression tests and explicit legacy behavior.
3. Reconcile privacy export/delete/retention of newly selected operational stores,
   and verify representative integrated ingest/search/failure/retry while workers run.
4. Complete deployment-specific migration/parity/rollback and readiness validation;
   no operator deployment or production credentials were used in this audit.

The Python sqlite3.connect sentinel detects Python relational SQLite access in
executed paths; Chroma native vector persistence is a separate boundary. It is
not a filesystem-wide proof that no SQLite-format vector files exist.

Research check: [Postgres 16 locking documentation](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE)
confirms SKIP LOCKED is appropriate for competing queue consumers but does not
provide a complete consistent view. Keep exclusive-claim/retry tests and avoid
using queue polling as proof of global job inventory completeness. No framework
or dependency added.

## Historical inventory (superseded)

### Original P-03 relational SQLite audit

Audit baseline: `e205873cccc8bd973dfed37c4b811540240e3b80` (PR #166), 2026-09-10. P-03 remains **Partial**.

## Method and boundary

Reviewed direct `sqlite3`, schema helpers, `migrate`, and `FTSIndex` imports across `app/`, their callers, backend selectors, and relevant tests. The table separates selected local implementations from runtime bypasses. It is a static call-path inventory, not a claim of complete dynamic zero-write proof. Chroma's own vector persistence is outside this relational SQLite retirement claim.

| Surface / implementation | Remaining behavior and required work |
| --- | --- |
| `app/main.py:lifespan`, `services/ingest_service.py:IngestService.__init__` | PRs #243 and #245 gate legacy migration on the selected Postgres profile. Constructor regression coverage is merged; full ingest/worker execution remains required. |
| `services/connector_ingest_service.py` | Baseline directly constructed SQLite FTS, persisted capsule JSON via the legacy helper, and advanced SQLite cache metadata. These now use selected FTS, artifact and cache stores and pass exact tenant identity to lexical/artifact mutations. Direct constructor migration is removed. Cross-source dedup now routes through a selected tenant-scoped content URL index store aligned with `memory_store_backend`. |
| `services/cross_duplicate_service.py` | Direct `content_url_index` SQLite access is removed. SQLite remains the local implementation; Postgres selection is fail-closed through the shared runtime and content-hash duplicate selection is deterministic by `(created_at, url_hash)`. A guarded exact-tenant migration now copies legacy rows from one read-only SQLite snapshot, preserves target-authoritative rows, validates source identity coverage inside the target transaction, and reports counts only. Live production execution/full-profile validation remain open. |
| `services/memory_intelligence_service.py` | Capsule reads now follow the selected tenant-scoped artifact store. Agent/extension searches are mirrored into the canonical intelligence event stream; insights now reads that stream only, avoiding the legacy `agent_search_events` SQLite bypass and mirrored-query double counting. The underlying `IntelligenceStore` remains SQLite and is tracked separately below. |
| `db/intelligence_store.py` | Topic profiles/links, learning edges, concept capsules, creator profiles and intelligence events remain SQLite. |
| `db/knowledge_graph_store.py`, `services/entity_merge_service.py` | Graph entities, relations and memory links remain SQLite. Migration must preserve canonical links, temporal evidence, tenant isolation and explicit merge confirmation. |
| `services/agent_runtime.py`, `ingest_agent.py`, `agent_status_service.py`, `review_schedule_service.py` | Agent definitions/runs/steps, ingest rules/claims, search activity and review schedules use SQLite. Preserve approval, dedup and replay contracts during routing/transfer. |
| `services/event_bus.py` | Event/audit and subscriber-delivery persistence still uses schema connections. Postgres jobs plus Redis wake transport do not migrate these records. |
| `services/oauth_token_vault.py` | Encrypted connector-token persistence remains SQLite. Preserve environment-owned encryption keys; token payloads must never enter migration reports. |
| `services/privacy_service.py` | Privacy deletion of `content_url_index`, YouTube memory export/deletion, capture export, bookmark export, and background-job export now route through selected tenant-scoped SQLite/Postgres backends. User and topic-profile export reads plus graph/intelligence, trust/version/lifecycle and capsule deletion still directly access SQLite and must be migrated in bounded slices before production cutover; preserve confirmation and retention contracts. |
| `services/feedback_service.py`, `model_router.py` | Feedback/routing feedback use direct SQLite connections. Need selected durable storage and tenant/privacy verification. |
| `db/sqlite_client.py` | Explicit SQLite registry adapter reads/deletes registry/reflection rows. Audit consumers before retiring the adapter. |
| `db/auth_store.py`, `memory_store.py`, `video_registry.py`, `capture_store.py`, `bookmark_store.py`, `import_run_store.py`, `job_store.py`, `youtube_memory_store.py`, `sqlite_youtube_memory_store.py`, `sqlite_ingest_artifact_store.py` | Local SQLite implementations remain intentional; production selectors exist. Direct construction and downstream consumers must still be exercised in the full production profile. |
| `services/fts_index.py`, `semantic_cache.py`, `db/schema.py`, legacy `db/hierarchical_store.py:store_capsule_json` | SQLite implementations/helpers remain for local mode. Selected stores must be used by every production caller; helper existence alone does not prove runtime reachability. |
| `db/postgres_*_migration.py`, `fts_retrieval_parity.py` | Intentional legacy source reads. Do not count migration source reads as production writes. Legacy FTS ownership handling and deployment-wide real-Postgres parity still need final acceptance evidence. |

## Validated scope of connector regression

`tests/test_connector_storage_routing.py` executes real PDF connector parsing and the real generic ingest method. It checks capsule/section/evidence tenant forwarding, canonical metadata and dedup registration, selected cache invalidation, hierarchy on/off behavior, authenticated SQLite lexical rejection, and missing-DSN failure with no fallback. Unrelated vector/canonical dependencies are isolated; therefore the no-SQLite-file assertion applies only to this routing boundary, not to the whole application.

The existing offline web, PDF and GitHub ingest suite remains part of validation. The artifact selector continues to share `YOUTUBE_STORE_BACKEND`; this also controls the common capsule artifact table for generic connectors. Cross-source URL/content dedup now follows `MEMORY_STORE_BACKEND` so canonical memory and its duplicate index cannot intentionally select different durable backends.

## Next acceptance work

1. Validate real-Postgres lexical retrieval parity without schema writes, including a mismatch that keeps the gate closed. Representative fixture success is not deployment-wide parity certification.
2. Execute/validate the guarded `content_url_index` migration against real Postgres, then complete privacy export/deletion routing before live cutover; the Memory Intelligence capsule/search-read bypasses are now removed.
3. Migrate the remaining stores above and their canonical/approval relationships in bounded slices.
4. Only then remove global SQLite initialization and prove startup, ingestion, retrieval, mutation, export/delete, worker retry and failure paths perform zero unintended relational SQLite writes with Postgres selected.

No production data was migrated; no full P-03 or Jarvis-transition completion is claimed.

## Runtime acceptance update — 2026-09-13

#246 gates PrivacyService migration; #247 and #248 prove selected import/graph
runtime persistence without SQLite connections. #249 exercises selected relational
privacy construction, lexical search, export and delete against real Postgres with
a SQLite sentinel. It repairs shared-source lexical deletion and tests failure/retry
without losing canonical ownership. CI: 1,027 passed. Chroma is isolated in this
proof; full multi-worker production acceptance remains open. The older table is
a historical inventory and must be re-audited against current selected factories.

## Runtime audit continuation — 2026-09-14

Verified main: `066fe45c52b59e0590c8b5e3e5499a98500c350f` (#258).
#252–#258 (excluding the unmerged Career PR #255) supply bounded lexical parity,
worker and ingest success/failure/concurrency acceptance. The older table is not
an instruction to rebuild selected graph, topic, edge, capsule, creator, event,
import or privacy stores already merged.

ReviewScheduleService still directly opened SQLite in this main revision. The
current slice routes its metadata to Postgres with `memory_store_backend` and
retains exact tenant/video identity and ownership checks. Counts use a single
`INSERT ... ON CONFLICT DO UPDATE ... RETURNING` to avoid lost updates across
workers, following [Postgres 16 INSERT semantics](https://www.postgresql.org/docs/16/sql-insert.html).
No new dependency is needed. Regression tests require real Postgres for concurrent
updates, rollback/retry and tenant isolation; missing-DSN failure runs locally.
Legacy schedule migration and privacy export/delete remain acceptance work.
AgentRuntime, IngestAgent, AgentStatusService, EventBus, OAuthTokenVault,
FeedbackService and ModelRouter usage accounting still have direct SQLite paths.
Full production-profile SQLite retirement is not claimed.

Review schedule runtime routing passed real-Postgres CI in #259 (1,056 tests).
The privacy follow-up exports tenant-filtered schedules and deletes exact-tenant
review metadata before canonical ownership. Injected deletion failure preserves
ownership for retry. Legacy review migration still remains; this is not a full
privacy inventory closeout or production SQLite retirement.

#260 privacy acceptance passed CI with 1,058 Python tests. The review migration
slice adds explicit-owner preview/apply with read-only source validation and
transactional target inserts. Its exact-head PR CI is the acceptance authority.
Next bounded runtime slice: EventBus, then dependent AgentRuntime/ingest rules
and OAuth vault, followed by agent status and feedback/model-usage accounting.
The final broad audit must also check direct registry adapters and selected
factory callers; this list is not proof that no other bypass exists.

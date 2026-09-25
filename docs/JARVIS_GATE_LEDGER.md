# Memory Search gate evidence ledger

Updated: 2026-09-25.

**Jarvis Gate: 27/29 cleared — 2 remaining.** The source-of-truth acceptance inventory is reconciled against dedicated closeouts for previously stale N/U backlog labels; G15 and G02 remain accepted.

P-03/G26 implementation acceptance is complete (#354/#356). U-03/G27's
repository-controlled composition contract is accepted (#370/#373). Their older
Partial/Not Started labels were stale; reconciling them does not earn another
checkpoint. Current starting main is `cd3d2e61690dbf53943eb49fe938897ce74d4c7c`,
verified by [main CI #1349](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/36016762611).

The basis for the single 24 → 25 advancement is the existing **G02 retrieval
and search isolation** contract. Review found ambiguous tenant/source vector IDs,
so documentation alone could not close it. See [G02 acceptance](G02_RETRIEVAL_ISOLATION_ACCEPTANCE.md)
for the repair and regression evidence. G28 was already Complete; G29 remains
Partial. No P-03, U-03, release, Home or Vision work is counted again.

The running count carries forward the documented P-03 23/29 closeout and the
accepted U-03 continuation to 24/29, plus this G02 acceptance to 25/29. It is not a sum of the G-rows: these rows were
introduced as a candidate normalization and do not reconstruct the missing
historical 29-item mapping. That reconciliation remains explicitly under G29;
this change neither invents four remaining identities nor declares the final
Jarvis transition complete.

Unchanged rows below retain their prior scoped acceptance evidence. “CI baseline
1068” refers to PR #272 head `e64a3e16c72f7d869203cb1720bf29e2129364b1`,
[run 34836155411](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/34836155411).
Later accepted rows cite their own closeouts; deployment evidence is never inferred
from automated repository checks.

## G01 — Ingest and evidence indexing

- Source IDs: F-02–08; V1-2. Status: **Complete**.
- Acceptance: Normalize source identity; bounded fetch/chunk/embed; idempotent indexing.
- Implementation: `app/services/ingest_service.py`. Source contract: `docs/V1_2_YOUTUBE_AGENT.md`.
- Source revision: `769b3e8 Release v1.9.0 - AHME (AI Hybrid Memory Engine)`. CI: baseline 1068 above; coverage: `tests/test_ingest*.py`.
- Remaining: None within accepted baseline; production orchestration belongs to G26.

## G02 — Retrieval and search isolation

- Source IDs: F-09–10. Status: **Complete**.
- Acceptance: Hierarchical and flat search preserve tenant evidence and metadata.
- Implementation: `app/services/ahme_engine.py`, `app/services/search_service.py`, `app/db/vector_identity.py`, vector repositories and canonical embedding references.
- Evidence: [G02 acceptance](G02_RETRIEVAL_ISOLATION_ACCEPTANCE.md); PR #382 repairs ambiguous vector identities and adds real-Chroma collision/replay/reference proof plus real-Postgres flat/hierarchical/fallback SearchService acceptance.
- Validation: implementation head `c8b2675462d32ed81aba942dbfeb08d6385326c9` passed [CI #1350](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/36178736364), including real PostgreSQL/Redis tests, 27 extension tests, version agreement and benchmark. The final documentation head must also pass required CI before merge.

## G03 — Grounded chat and optional AI

- Source IDs: F-11–13, F-16. Status: **Complete**.
- Acceptance: Cited grounded answers; deterministic fallback; provider failures handled.
- Implementation: `app/services/chat_service.py`. Source contract: `docs/F12_ANSWER_SYNTHESIS_CLOSEOUT.md`.
- Source revision: `4aa622c docs: record F-12 synthesis closeout evidence (#77)`. CI: baseline 1068 above; coverage: `tests/test_grounded_synthesis_llm.py`.
- Remaining: None in documented contract; no mandatory provider calls.

## G04 — Reflection and enrichment

- Source IDs: F-14–15, F-17. Status: **Complete**.
- Acceptance: Tenant-local saved context and bounded ranking preserve evidence scores.
- Implementation: `app/services/search_service.py`. Source contract: `docs/PHASE2_MEMORY_INTELLIGENCE_CLOSEOUT.md`.
- Source revision: `3524162 Phase 2 Memory Intelligence closeout`. CI: baseline 1068 above; coverage: `tests/test_search_service.py`.
- Remaining: None in baseline; production telemetry covered under G26.

## G05 — Configuration and local persistence

- Source IDs: F-01, F-26, F-30. Status: **Complete**.
- Acceptance: Injectable settings; idempotent local migrations; tenant-scoped registry adapter.
- Implementation: `app/db/sqlite_client.py`. Source contract: `docs/closeouts/F30_SQLITE_REGISTRY_CLIENT.md`.
- Source revision: `6b3cbe8 F-30: record validated SQLite registry client closeout (#79)`. CI: baseline 1068 above; coverage: `tests/test_sqlite_registry_client.py`.
- Remaining: Local adapter is intentional; never instantiate it for production Postgres.

## G06 — Authentication and tenant keys

- Source IDs: F-19, F-31, P-06. Status: **Complete**.
- Acceptance: Session lifecycle and composite ownership enforce authenticated boundaries.
- Implementation: `app/db/auth_store.py`. Source contract: `docs/V1_8_AUTH_PRIVACY.md`.
- Source revision: `769b3e8 Release v1.9.0 - AHME (AI Hybrid Memory Engine)`. CI: baseline 1068 above; coverage: `tests/test_v1_8_auth_privacy.py`.
- Remaining: Production-wide isolation remains G26/G29; feature closeout is scoped.

## G07 — Durable jobs and multi-worker claims

- Source IDs: F-20, F-35, P-08. Status: **Complete**.
- Acceptance: Preview/confirm; durable claims/leases; safe retries and split-worker selection.
- Implementation: `app/services/job_worker.py`. Source contract: `docs/closeouts/RUNTIME_PLATFORM_CLOSEOUT.md`.
- Source revision: `358815c Roadmap: close out validated runtime platform milestones (#74)`. CI: baseline 1068 above; coverage: `tests/test_postgres_job_worker*.py`.
- Remaining: None in validated job contract (#253, #254, #256); app lifecycle acceptance is G26.

## G08 — Explicit capture and URL safety

- Source IDs: F-21; V1-01–02. Status: **Complete**.
- Acceptance: Explicit capture retains SSRF checks, provenance and async status.
- Implementation: `app/services/capture_service.py`. Source contract: `docs/V1_1_IMPLEMENTATION.md`.
- Source revision: `769b3e8 Release v1.9.0 - AHME (AI Hybrid Memory Engine)`. CI: baseline 1068 above; coverage: `tests/test_capture*.py`.
- Remaining: No ambient capture or extra permissions implied.

## G09 — Extension source workflows

- Source IDs: F-22; V1-03,07,08,11,12. Status: **Complete**.
- Acceptance: Safe metadata extraction, repository save/starred import and explicit command UX.
- Implementation: `extension`. Source contract: `docs/closeouts/V1_08_GITHUB_STARRED_IMPORT_CLOSEOUT.md`.
- Source revision: `00900ec V1-08: add confirmation-gated GitHub starred import`. CI: baseline 1068 above; coverage: `tests/extension/*.mjs`.
- Remaining: Provider setup remains external; current repository-controlled scope only.

## G10 — Workspace and offline UX

- Source IDs: F-18, F-24; U-01,02,04. Status: **Complete**.
- Acceptance: Unified input, date/goal timeline and bounded retry-preserving offline capture.
- Implementation: `app/static`. Source contract: `docs/U04_OFFLINE_INGEST_QUEUE_ACCEPTANCE.md`.
- Source revision: `0a4d2e7 U-04: add privacy-safe offline URL ingest queue`. CI: baseline 1068 above; coverage: `tests/test_offline_capture_ui.py`.
- Remaining: No background/autonomous capture; also see U01/U02 closeouts and acceptance tests.

## G11 — Bookmark imports

- Source IDs: F-23; V1-06. Status: **Complete**.
- Acceptance: Preview and opt-in re-import preserve deterministic dedup and totals.
- Implementation: `See implementation paths in docs/F23_BOOKMARK_IMPORT_CLOSEOUT.md`. Source contract: `docs/F23_BOOKMARK_IMPORT_CLOSEOUT.md`.
- Source revision: `0612e18 F-23: validate opt-in bookmark resync and closeout`. CI: baseline 1068 above; coverage: `tests/test_phase3_bookmark_sync.py`.
- Remaining: None within accepted contract.

## G12 — Connector framework

- Source IDs: F-29; C-01. Status: **Complete**.
- Acceptance: Normalized registry contract and canonical provenance-preserving ingest.
- Implementation: `app/services/connector_ingest_service.py`. Source contract: `docs/F29_CONNECTOR_SDK_CLOSEOUT.md`.
- Source revision: `d11dccb F-29: lock connector SDK contract and closeout evidence (#72)`. CI: baseline 1068 above; coverage: `tests/test_connector_sdk_contract.py`.
- Remaining: Full production execution across representative connectors remains G26.

## G13 — OAuth credential boundary

- Source IDs: C-02. Status: **Complete**.
- Acceptance: Tenant-scoped encryption, rotation/revoke and redacted lifecycle events.
- Implementation: `app/services/oauth_token_vault.py`. Source contract: `docs/closeouts/C02_OAUTH_ADAPTER_FRAMEWORK.md`.
- Source revision: `d4250bd C-02: lock OAuth adapter framework acceptance`. CI: baseline 1068 above; coverage: `tests/test_postgres_oauth_token_vault.py`.
- Remaining: Live provider consent/app approval is external; PG routing merged #263.

## G14 — Supported content connectors

- Source IDs: C-03–07; V1-09–10. Status: **Complete**.
- Acceptance: Safe web, Docs/PDF, bounded Notion ZIP, Readwise and RSS shownotes ingest.
- Implementation: `app/services/sources`. Source contract: `CONNECTOR_SDK.md`.
- Source revision: `769b3e8 Release v1.9.0 - AHME (AI Hybrid Memory Engine)`. CI: baseline 1068 above; coverage: `tests/test_universal_connectors.py`.
- Remaining: Scope follows individual C03–C07 closeouts; no audio transcription/live Notion claim.

## G15 — Privacy and portable export

- Source IDs: C-08; V1-14. Status: **Complete**.
- Acceptance: Owned export/delete, lossless Markdown, derived-data deletion and retry safety.
- Implementation: `app/services/privacy_service.py`. Source contract: `docs/closeouts/C08_EXPORT_ADAPTER.md`.
- Evidence: `FEATURE_IDEAS.md` marks both C-08 and V1-14 Complete. C-08's closeout records authenticated tenant-scoped full export plus lossless Markdown round-trip acceptance. P-03's later #351/#354/#356 acceptance extends this boundary through complete production export, operational-history coverage, exact-account confirmed erasure, durable fencing, stale/late-worker protection, neighbor preservation, and retry-safe residual cleanup on real Postgres.
- Validation: C-08 PR #107 CI #682 passed its round-trip acceptance; P-03 implementation closeout records PR #354 exact head `5251e16be39e6d4c7d4ccccfc7f36514d6ed6cf8` passing required CI #1291 and Home Vision Smoke #40 before merge. Existing privacy suites cover production export/delete and combined real-Postgres acceptance; no live-deployment purge is inferred from CI.
- Remaining: None in the repository-controlled C-08/V1-14 contract. Live-deployment physical purge/backup-retention evidence remains an operator prerequisite and is not required to claim repository implementation acceptance.

## G16 — Canonical records and lifecycle

- Source IDs: F-36–37. Status: **Complete**.
- Acceptance: Canonical IDs, provenance, version history and explicit lifecycle transitions.
- Implementation: `app/db/memory_store.py`. Source contract: `MASTER_SPEC.md`.
- Source revision: `769b3e8 Release v1.9.0 - AHME (AI Hybrid Memory Engine)`. CI: baseline 1068 above; coverage: `tests/test_memory_lifecycle.py`.
- Remaining: No evidence reset; production migration acceptance belongs to G26.

## G17 — Graph and entity merge

- Source IDs: F-33; N-05. Status: **Complete**.
- Acceptance: Temporal facts, tenant-safe entity merge and explicit confirmation.
- Implementation: `app/services/entity_merge_service.py`. Source contract: `docs/closeouts/F33_KNOWLEDGE_GRAPH_CLOSEOUT.md`.
- Source revision: `4c466d7 F-33: close knowledge graph temporal and entity-merge acceptance (#94)`. CI: baseline 1068 above; coverage: `tests/test_knowledge_graph*.py`.
- Remaining: PG runtime accepted #248; operator cutover remains G26.

## G18 — Consensus

- Source IDs: N-01. Status: **Complete**.
- Acceptance: Independent source agreement without collapsing contradictions.
- Implementation: `app/services/consensus_engine.py`. Source contract: `docs/closeouts/N01_CONSENSUS_ENGINE_CLOSEOUT.md`.
- Source revision: `43325fe N-01: lock consensus engine acceptance`. CI: baseline 1068 above; coverage: `tests/test_consensus_acceptance.py`.
- Remaining: None within documented boundary.

## G19 — Verification

- Source IDs: N-02. Status: **Complete**.
- Acceptance: Deterministic per-claim grounding in evidence.
- Implementation: `app/services/verification_engine.py`. Source contract: `docs/N02_VERIFICATION_CLOSEOUT.md`.
- Source revision: `7f85462 N-02: record verification engine acceptance closeout (#76)`. CI: baseline 1068 above; coverage: `tests/test_verification_engine.py`.
- Remaining: Future policy enhancements remain separate.

## G20 — Trust and visible confidence

- Source IDs: N-03; F-38; U-06. Status: **Complete**.
- Acceptance: Interpretable persisted trust and safely escaped result badges.
- Implementation: `app/services/trust_engine.py`. Source contract: `docs/closeouts/N03_TRUST_ENGINE_CLOSEOUT.md`.
- Source revision: `c625e96 N-03: record trust engine acceptance`. CI: baseline 1068 above; coverage: `tests/test_trust_badges.py`.
- Remaining: No autonomous trust-based irreversible actions.

## G21 — Gaps and learning paths

- Source IDs: N-04, N-06; V1-13. Status: **Complete**.
- Acceptance: Evidence-backed gaps and deterministic next-learning recommendations.
- Implementation: `See implementation paths in docs/V1_13_LEARNING_PATH_ACCEPTANCE.md`. Source contract: `docs/V1_13_LEARNING_PATH_ACCEPTANCE.md`.
- Source revision: `e271c57 V1-13: lock evidence-backed learning path acceptance`. CI: baseline 1068 above; coverage: `tests/test_learning_path_acceptance.py`.
- Remaining: No invented curriculum or mandatory AI.

## G22 — Learning evolution

- Source IDs: N-07. Status: **Complete**.
- Acceptance: Bounded tenant-local ranking feedback without evidence mutation.
- Implementation: `app/services/learning_evolution_service.py`. Source contract: `docs/closeouts/N07_LEARNING_EVOLUTION_CLOSEOUT.md`.
- Source revision: `2770633 N-04: record Gap Engine acceptance closeout`. CI: baseline 1068 above; coverage: `tests/test_learning_evolution_acceptance.py`.
- Remaining: None in accepted baseline.

## G23 — Cross-source duplicate review

- Source IDs: N-08. Status: **Complete**.
- Acceptance: Deterministic duplicate candidates and confirmation-gated safe merge.
- Implementation: `app/services/cross_duplicate_service.py`. Source contract: `docs/N08_CROSS_SOURCE_DEDUP_ACCEPTANCE.md`.
- Source revision: `8379bd1 N-08: record cross-source dedup UI acceptance`. CI: baseline 1068 above; coverage: `tests/*duplicate*.py`.
- Remaining: Migration deployment remains G26.

## G24 — Memory agents and audit

- Source IDs: F-32, F-34; A-01–07. Status: **Complete**.
- Acceptance: Typed deterministic tools, tenant ownership, approval gates and durable events.
- Implementation: `app/services/agent_runtime.py`. Source contract: `AGENT_BIBLE.md`.
- Source revision: `62f021c Docs: reconcile implemented agent system (#113)`. CI: baseline 1068 above; coverage: `tests/test_agent_runtime.py`.
- Remaining: Accepted Memory agents only; no Career/Home continuation; PG #262/#264/#265/#266.

## G25 — Operations and test infrastructure

- Source IDs: F-25,27,28; P-01,02,04,05. Status: **Complete**.
- Acceptance: Health split, rate limits, metrics, reproducible benchmark and test-gated changes.
- Implementation: `app/middleware`. Source contract: `docs/F27_F28_OPS_TOOLING_CLOSEOUT.md`.
- Source revision: `b5d77d9 Docs: close F-27/F-28 ops tooling acceptance (#99)`. CI: baseline 1068 above; coverage: `tests/test_health.py`.
- Remaining: Postgres readiness and deployment checks remain G26/G29; no managed observability claim.

## G26 — Production Postgres acceptance

- Source IDs: P-03 / GAP-02. Status: **Complete — repository implementation acceptance**.
- Acceptance: All supported relational operations select Postgres; zero unintended SQLite writes; safe migration, retry and isolation.
- Implementation: `app/db/production_storage_profile.py`, selected stores and durable account-erasure fencing.
- Evidence: [P-03 closeout](P03_IMPLEMENTATION_CLOSEOUT_2026-09-22.md); #354 head `5251e16be39e6d4c7d4ccccfc7f36514d6ed6cf8`, CI #1291, merge `9bbb4310a98fccef2e9e06ad8538c1b3830ac155`; #356 records the closeout. Regression: `tests/test_postgres_account_fence_acceptance.py`, `tests/test_postgres_combined_privacy_acceptance.py`, production lifespan, migration and privacy suites.
- External only: actual legacy-deployment cutover/parity/readiness/rollback and backup/WAL/replica retention. No live deployment migration or physical purge is claimed.

## G27 — Daily briefing

- Source IDs: U-03. Status: **Complete — repository-controlled composition contract**.
- Acceptance: Grounded opt-in daily review/gap digest with explicit notification preferences.
- Implementation: `app/services/daily_briefing_service.py`.
- Evidence: [U-03 acceptance](U03_DAILY_BRIEFING_ACCEPTANCE.md); #370 head `20f4f49302f141ec2cb8a6df468055e2b5b24d26`, CI #1326 / run 35891508819, merge `1b0a50fb275fe6ba0ee2b5b3686ea68e108eb2b2`; #373 adds acceptance evidence. Regression: `tests/test_daily_briefing_service.py`.
- Boundary: deterministic tenant-safe bounded composition, evidence retention and two explicit notification opt-ins. No autonomous scheduler or OS/provider delivery is claimed.

## G28 — Release package

- Source IDs: V1-0–9 release packaging. Status: **Complete**.
- Acceptance: Version/manifest agree; reproducible demo/store materials and privacy disclosure.
- Implementation: `extension/manifest.json`. Source contract: `docs/V1_9_DEMO_STORE_LAUNCH.md`.
- Source revision: `769b3e8 Release v1.9.0 - AHME (AI Hybrid Memory Engine)`. CI: baseline 1068 above; coverage: `.github/workflows/ci.yml`.
- Remaining: Store publication/video recording remain human steps, explicitly outside package acceptance.

## G29 — Final version and transition reconciliation

- Source IDs: All-version acceptance/stability. Status: **Partial**.
- Acceptance: Every mandatory planned Memory acceptance has evidence; no reproducible isolation defects; inventory reconciled.
- Implementation: `docs/CURRENT_BUILD_STATE.md`. Source contract: `docs/SOURCE_OF_TRUTH_RECONCILIATION.md`.
- Source revision: `26591ab Docs: reconcile validated connectors and runtime platform (#110)`. CI: baseline 1068 above; coverage: `.github/workflows/ci.yml`.
- Remaining: Final historical/root-document reconciliation and exact-head stability validation. Previously stale mandatory N/U backlog labels are now tied to dedicated acceptance closeouts; deferred C-09/U-05 and optional P-07 are not pre-transition Memory Search requirements.

## Deferred scope and reconciliation limits

P-07 is explicitly optional remote embedding; C-09 is explicitly deferred native share; U-05 and voice/vision/gesture/spatial work are Jarvis-specific. None is silently marked Complete. All F-01–38, N-01–08, A-01–07, C-01–08, mandatory P/U rows and V1 feature/release boundaries are named above. Historical later-version roadmap language must still be compared against these scoped contracts before this candidate inventory becomes authoritative. Existing Home/Career code is preserved but does not clear a Memory Search row.

# Memory Search source-of-truth reconciliation

Updated: 2026-09-26.

**Jarvis Gate: 28/29 cleared — 1 remaining.** This records the historical/root
acceptance reconciliation component of G29. Final transition/stability sign-off
remains open; this is not 29/29 or authorization to start Jarvis features.

## Baseline, classification and evidence rule

Starting main: `159cb2e7b82c5b6a28ccab170708ba09d653b7b9` (#384).
[Exact-main CI #1356](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/36207110852)
passed: **1,358 Python tests passed, 1 skipped**, extension helpers, version/manifest
agreement and AHME benchmark. That run includes the existing real PostgreSQL/Redis
acceptance suites referenced below. Its single skipped test is not treated as proof.
The reconciliation PR must pass its own exact-head CI before merging this status.

Each row below was checked against the actual implementation and regression
assertions, not accepted merely because a closeout exists. The complete current
suite supplies fresh CI evidence for the inherited contracts; per-feature closeouts
preserve the original narrower acceptance and historical validation. UI source
contract tests are identified as such below and are not live browser/provider proof.

Classifications: **CURRENT + COMPLETE**, **CURRENT + REAL GAP**,
**HISTORICAL/SUPERSEDED**, **OPTIONAL**, **DEFERRED/JARVIS**,
**EXTERNAL/HUMAN PREREQUISITE**. The only new reproducible implementation gap found
in this bounded reconciliation was U-04 account-switch replay; it is repaired and
behaviorally regression-covered here. No acceptance boundary was widened to claim
provider deployment or weakened to bypass a failure.

## Current mandatory acceptance matrix

Every row is **CURRENT + COMPLETE** at the stated repository-controlled boundary,
conditional on the reconciliation PR's required CI/merge gate. Baseline CI #1356
covers the inherited tests; the new U-04 regression is validated by this PR's CI.
The table is an evidence inventory, **not a sum of the historical 29-count**.

| IDs | Accepted requirement | Implementation inspected | Regression proof | Scoped acceptance record |
|---|---|---|---|---|
| F-12 | Grounded synthesis; rejected provider evidence falls back | [app/services/answer_synthesizer.py](../app/services/answer_synthesizer.py); [app/services/chat_service.py](../app/services/chat_service.py) | [tests/test_grounded_synthesis_llm.py](../tests/test_grounded_synthesis_llm.py); [tests/test_answer_synthesizer.py](../tests/test_answer_synthesizer.py) | [docs/F12_ANSWER_SYNTHESIS_CLOSEOUT.md](../docs/F12_ANSWER_SYNTHESIS_CLOSEOUT.md) |
| F-16 | Optional provider contracts; none/failure remains deterministic | [app/services/llm_provider.py](../app/services/llm_provider.py) | [tests/test_llm_provider.py](../tests/test_llm_provider.py) | [docs/F16_LLM_PROVIDER_CLOSEOUT.md](../docs/F16_LLM_PROVIDER_CLOSEOUT.md) |
| F-23 | Opt-in bookmark resync, complete snapshots and tenant dedup | [app/services/import_manager.py](../app/services/import_manager.py); [extension/background.js](../extension/background.js) | [tests/test_phase3_bookmark_sync.py](../tests/test_phase3_bookmark_sync.py); [tests/extension/test_bookmarks.mjs](../tests/extension/test_bookmarks.mjs) | [docs/F23_BOOKMARK_IMPORT_CLOSEOUT.md](../docs/F23_BOOKMARK_IMPORT_CLOSEOUT.md) |
| F-27 | Reproducible benchmark report and CI smoke | [scripts/benchmark_ahme.py](../scripts/benchmark_ahme.py); [.github/workflows/ci.yml](../.github/workflows/ci.yml) | [tests/test_ahme.py](../tests/test_ahme.py) | [docs/F27_F28_OPS_TOOLING_CLOSEOUT.md](../docs/F27_F28_OPS_TOOLING_CLOSEOUT.md) |
| F-28 | Ingest CLI; safe reset dry-run and explicit destructive confirmation | [scripts/ingest_item.py](../scripts/ingest_item.py); [scripts/reset_db.py](../scripts/reset_db.py) | [tests/test_cli_tools.py](../tests/test_cli_tools.py) | [docs/F27_F28_OPS_TOOLING_CLOSEOUT.md](../docs/F27_F28_OPS_TOOLING_CLOSEOUT.md) |
| F-29 / C-01 | Configured normalized connector contract and canonical provenance | [app/services/sources/base_source.py](../app/services/sources/base_source.py); [app/services/sources/__init__.py](../app/services/sources/__init__.py); [app/services/connector_ingest_service.py](../app/services/connector_ingest_service.py) | [tests/test_connector_sdk_contract.py](../tests/test_connector_sdk_contract.py); [tests/test_connector_registry_config.py](../tests/test_connector_registry_config.py); [tests/test_universal_connectors.py](../tests/test_universal_connectors.py) | [docs/F29_CONNECTOR_SDK_CLOSEOUT.md](../docs/F29_CONNECTOR_SDK_CLOSEOUT.md) |
| F-30 | Tenant-scoped local list/delete without vector scan | [app/db/sqlite_client.py](../app/db/sqlite_client.py) | [tests/test_sqlite_registry_client.py](../tests/test_sqlite_registry_client.py) | [docs/closeouts/F30_SQLITE_REGISTRY_CLIENT.md](../docs/closeouts/F30_SQLITE_REGISTRY_CLIENT.md) |
| F-33 / N-05 | Tenant graph/temporal facts; merge rewires provenance only after literal confirmation | [app/services/knowledge_graph_service.py](../app/services/knowledge_graph_service.py); [app/services/entity_merge_service.py](../app/services/entity_merge_service.py); [app/api/routes/knowledge.py](../app/api/routes/knowledge.py) | [tests/test_knowledge_graph.py](../tests/test_knowledge_graph.py); [tests/test_entity_merge.py](../tests/test_entity_merge.py); [tests/test_entity_merge_ui.py](../tests/test_entity_merge_ui.py) | [docs/closeouts/F33_KNOWLEDGE_GRAPH_CLOSEOUT.md](../docs/closeouts/F33_KNOWLEDGE_GRAPH_CLOSEOUT.md); [docs/closeouts/N05_KNOWLEDGE_GRAPH_STORE_CLOSEOUT.md](../docs/closeouts/N05_KNOWLEDGE_GRAPH_STORE_CLOSEOUT.md) |
| F-34 | Durable tenant events, correlation and recursive secret redaction | [app/services/event_bus.py](../app/services/event_bus.py) | [tests/test_event_bus.py](../tests/test_event_bus.py); [tests/test_postgres_event_bus.py](../tests/test_postgres_event_bus.py) | [docs/closeouts/RUNTIME_PLATFORM_CLOSEOUT.md](../docs/closeouts/RUNTIME_PLATFORM_CLOSEOUT.md) |
| F-35 / P-08 | Postgres authoritative claims/leases; Redis opaque wake; unsafe split mode rejected | [app/services/job_worker.py](../app/services/job_worker.py) | [tests/test_distributed_job_runtime_e2e.py](../tests/test_distributed_job_runtime_e2e.py); [tests/test_postgres_job_claims.py](../tests/test_postgres_job_claims.py); [tests/test_runtime_safety.py](../tests/test_runtime_safety.py) | [docs/closeouts/RUNTIME_PLATFORM_CLOSEOUT.md](../docs/closeouts/RUNTIME_PLATFORM_CLOSEOUT.md) |
| N-01 | Independent-source consensus retains conflict and visible weight | [app/services/consensus_engine.py](../app/services/consensus_engine.py); [app/services/chat_service.py](../app/services/chat_service.py) | [tests/test_consensus_engine.py](../tests/test_consensus_engine.py); [tests/test_consensus_acceptance.py](../tests/test_consensus_acceptance.py) | [docs/closeouts/N01_CONSENSUS_ENGINE_CLOSEOUT.md](../docs/closeouts/N01_CONSENSUS_ENGINE_CLOSEOUT.md) |
| N-02 | Per-claim evidence verification including unsupported numeric claims | [app/services/verification_engine.py](../app/services/verification_engine.py) | [tests/test_verification_engine.py](../tests/test_verification_engine.py) | [docs/N02_VERIFICATION_CLOSEOUT.md](../docs/N02_VERIFICATION_CLOSEOUT.md) |
| N-03 / U-06 | Persisted interpretable trust; tenant-scoped escaped badges | [app/services/trust_engine.py](../app/services/trust_engine.py); [app/services/search_service.py](../app/services/search_service.py) | [tests/test_trust_badges.py](../tests/test_trust_badges.py); [tests/test_universal_memory.py](../tests/test_universal_memory.py); [tests/extension/trust_badge.test.mjs](../tests/extension/trust_badge.test.mjs) | [docs/closeouts/N03_TRUST_ENGINE_CLOSEOUT.md](../docs/closeouts/N03_TRUST_ENGINE_CLOSEOUT.md) |
| N-04 / A-06 | Evidence-backed per-goal coverage/diversity/review gaps and actionable notifications | [app/services/gap_agent.py](../app/services/gap_agent.py) | [tests/test_gap_agent.py](../tests/test_gap_agent.py) | [docs/closeouts/N04_GAP_ENGINE_CLOSEOUT.md](../docs/closeouts/N04_GAP_ENGINE_CLOSEOUT.md) |
| N-06 | Deterministic next-learning actions from saved gaps; no invented material | [app/services/reverse_memory_service.py](../app/services/reverse_memory_service.py) | [tests/test_reverse_memory.py](../tests/test_reverse_memory.py) | [docs/closeouts/N06_REVERSE_MEMORY_CLOSEOUT.md](../docs/closeouts/N06_REVERSE_MEMORY_CLOSEOUT.md) |
| N-07 | Tenant feedback evolves ranking without re-ingest or evidence-score mutation | [app/services/learning_evolution_service.py](../app/services/learning_evolution_service.py); [app/services/search_service.py](../app/services/search_service.py) | [tests/test_learning_evolution.py](../tests/test_learning_evolution.py); [tests/test_learning_evolution_acceptance.py](../tests/test_learning_evolution_acceptance.py) | [docs/closeouts/N07_LEARNING_EVOLUTION_CLOSEOUT.md](../docs/closeouts/N07_LEARNING_EVOLUTION_CLOSEOUT.md) |
| N-08 | Canonical duplicate proposals and user-confirmed merge | [app/services/cross_duplicate_service.py](../app/services/cross_duplicate_service.py); [app/services/memory_intelligence_service.py](../app/services/memory_intelligence_service.py) | [tests/test_memory_intelligence.py](../tests/test_memory_intelligence.py); [tests/extension/duplicate_merge_ui.test.mjs](../tests/extension/duplicate_merge_ui.test.mjs) | [docs/N08_CROSS_SOURCE_DEDUP_ACCEPTANCE.md](../docs/N08_CROSS_SOURCE_DEDUP_ACCEPTANCE.md) |
| A-01 / F-32 | Typed deterministic runtime, tenant lookup, approval-gated writes and audit | [app/services/agent_runtime.py](../app/services/agent_runtime.py); [app/api/routes/agents.py](../app/api/routes/agents.py) | [tests/test_agent_runtime.py](../tests/test_agent_runtime.py); [tests/test_postgres_agent_runtime_privacy.py](../tests/test_postgres_agent_runtime_privacy.py) | [docs/closeouts/A01_AGENT_RUNTIME.md](../docs/closeouts/A01_AGENT_RUNTIME.md) |
| A-02 | Inert rules until approved; canonical dedup and retry claims | [app/services/ingest_agent.py](../app/services/ingest_agent.py) | [tests/test_ingest_agent.py](../tests/test_ingest_agent.py); [tests/test_ingest_agent_api.py](../tests/test_ingest_agent_api.py) | [AGENT_BIBLE.md](../AGENT_BIBLE.md) |
| A-03 | Bounded research with at least three distinct cited saved sources | [app/services/research_agent.py](../app/services/research_agent.py) | [tests/test_research_agent.py](../tests/test_research_agent.py) | [docs/closeouts/A03_RESEARCH_AGENT.md](../docs/closeouts/A03_RESEARCH_AGENT.md) |
| A-04 | Active-goal review, 14-day stale boundary and durable due dates | [app/services/review_agent.py](../app/services/review_agent.py) | [tests/test_review_agent.py](../tests/test_review_agent.py); [tests/test_review_schedule.py](../tests/test_review_schedule.py) | [docs/closeouts/A04_REVIEW_AGENT.md](../docs/closeouts/A04_REVIEW_AGENT.md) |
| A-05 | Read-only triage rejects unsafe URLs and tenant-local duplicates | [app/services/capture_triage_agent.py](../app/services/capture_triage_agent.py) | [tests/test_capture_triage_agent.py](../tests/test_capture_triage_agent.py) | [docs/closeouts/A05_CAPTURE_TRIAGE_AGENT.md](../docs/closeouts/A05_CAPTURE_TRIAGE_AGENT.md) |
| A-07 | Read-only consolidation; separate authenticated confirmed merge | [app/services/consolidation_agent.py](../app/services/consolidation_agent.py) | [tests/test_consolidation_agent.py](../tests/test_consolidation_agent.py); [tests/test_entity_merge.py](../tests/test_entity_merge.py) | [docs/closeouts/A07_CONSOLIDATION_AGENT.md](../docs/closeouts/A07_CONSOLIDATION_AGENT.md) |
| C-02 | Encrypted tenant credentials, refresh/rotation/revoke, secret-safe audit | [app/services/oauth_token_vault.py](../app/services/oauth_token_vault.py); [app/api/routes/connector_auth.py](../app/api/routes/connector_auth.py) | [tests/test_oauth_token_vault.py](../tests/test_oauth_token_vault.py); [tests/test_postgres_oauth_token_vault.py](../tests/test_postgres_oauth_token_vault.py) | [docs/closeouts/C02_OAUTH_ADAPTER_FRAMEWORK.md](../docs/closeouts/C02_OAUTH_ADAPTER_FRAMEWORK.md) |
| C-03 | SSRF-safe HTML normalization through shared canonical ingest | [app/services/sources/web_connector.py](../app/services/sources/web_connector.py); [app/services/ssrf_fetch.py](../app/services/ssrf_fetch.py) | [tests/test_universal_connectors.py](../tests/test_universal_connectors.py) | [docs/closeouts/C03_WEB_ARTICLE_CONNECTOR.md](../docs/closeouts/C03_WEB_ARTICLE_CONNECTOR.md) |
| C-04 | Scoped Docs/PDF import and bounded secret-safe provider errors | [app/services/gdrive_import_service.py](../app/services/gdrive_import_service.py); [app/services/sources/gdrive_connector.py](../app/services/sources/gdrive_connector.py) | [tests/test_gdrive_connector.py](../tests/test_gdrive_connector.py); [tests/test_gdrive_acceptance.py](../tests/test_gdrive_acceptance.py) | [docs/closeouts/C04_GOOGLE_DRIVE_CONNECTOR.md](../docs/closeouts/C04_GOOGLE_DRIVE_CONNECTOR.md) |
| C-05 | Bounded offline ZIP/Markdown import, safe paths, provenance and dedup | [app/services/notion_import_service.py](../app/services/notion_import_service.py); [app/services/sources/notion_connector.py](../app/services/sources/notion_connector.py) | [tests/test_notion_import.py](../tests/test_notion_import.py) | [docs/closeouts/C05_NOTION_EXPORT_CONNECTOR.md](../docs/closeouts/C05_NOTION_EXPORT_CONNECTOR.md) |
| C-06 | CSV highlights become evidence; repeated rows collapse while tags survive | [app/services/readwise_import_service.py](../app/services/readwise_import_service.py); [app/services/sources/readwise_connector.py](../app/services/sources/readwise_connector.py) | [tests/test_readwise_import.py](../tests/test_readwise_import.py) | [docs/closeouts/C06_READWISE_BRIDGE.md](../docs/closeouts/C06_READWISE_BRIDGE.md) |
| C-07 | Bounded SSRF-safe RSS/Atom show notes, stable episode ID and tenant forwarding | [app/services/podcast_import_service.py](../app/services/podcast_import_service.py); [app/services/sources/podcast_connector.py](../app/services/sources/podcast_connector.py) | [tests/test_podcast_connector.py](../tests/test_podcast_connector.py); [tests/test_podcast_acceptance.py](../tests/test_podcast_acceptance.py) | [docs/closeouts/C07_PODCAST_RSS_CONNECTOR.md](../docs/closeouts/C07_PODCAST_RSS_CONNECTOR.md) |
| C-08 / G15 | Full tenant export; versioned lossless Markdown parsing without implicit write | [app/services/privacy_service.py](../app/services/privacy_service.py) | [tests/test_markdown_export.py](../tests/test_markdown_export.py); [tests/test_postgres_complete_privacy_export.py](../tests/test_postgres_complete_privacy_export.py) | [docs/closeouts/C08_EXPORT_ADAPTER.md](../docs/closeouts/C08_EXPORT_ADAPTER.md) |
| P-01 | Dependency-independent liveness and fail-closed selected-store readiness | [app/api/routes/health.py](../app/api/routes/health.py) | [tests/test_health.py](../tests/test_health.py) | [docs/P01_READINESS_LIVENESS_CLOSEOUT.md](../docs/P01_READINESS_LIVENESS_CLOSEOUT.md) |
| P-03 / G26 | Complete selected Postgres profile, confirmed erasure/fence and idempotent migration | [app/db/production_storage_profile.py](../app/db/production_storage_profile.py); [app/services/privacy_erasure.py](../app/services/privacy_erasure.py); [app/db/account_erasure_fence.py](../app/db/account_erasure_fence.py) | [tests/test_postgres_account_fence_acceptance.py](../tests/test_postgres_account_fence_acceptance.py); [tests/test_postgres_combined_privacy_acceptance.py](../tests/test_postgres_combined_privacy_acceptance.py); [tests/test_postgres_production_lifespan.py](../tests/test_postgres_production_lifespan.py) | [docs/P03_IMPLEMENTATION_CLOSEOUT_2026-09-22.md](../docs/P03_IMPLEMENTATION_CLOSEOUT_2026-09-22.md) |
| P-04 | Privacy-safe Prometheus exposition and retained JSON snapshot | [app/api/routes/health.py](../app/api/routes/health.py); [app/middleware/observability.py](../app/middleware/observability.py) | [tests/test_observability.py](../tests/test_observability.py) | [docs/P04_PROMETHEUS_METRICS_CLOSEOUT.md](../docs/P04_PROMETHEUS_METRICS_CLOSEOUT.md) |
| U-01 | Single search/ask/capture input with explicit bulk confirmation | [extension/popup.js](../extension/popup.js) | [tests/test_unified_command_acceptance.py](../tests/test_unified_command_acceptance.py) | [docs/closeouts/U01_UNIFIED_COMMAND_BAR_CLOSEOUT.md](../docs/closeouts/U01_UNIFIED_COMMAND_BAR_CLOSEOUT.md) |
| U-02 | Date grouping and tenant goal/topic timeline | [app/services/memory_intelligence_service.py](../app/services/memory_intelligence_service.py) | [tests/test_timeline_acceptance.py](../tests/test_timeline_acceptance.py) | [docs/closeouts/U02_MEMORY_TIMELINE_CLOSEOUT.md](../docs/closeouts/U02_MEMORY_TIMELINE_CLOSEOUT.md) |
| U-03 / G27 | Deterministic bounded tenant briefing with two notification opt-ins | [app/services/daily_briefing_service.py](../app/services/daily_briefing_service.py) | [tests/test_daily_briefing_service.py](../tests/test_daily_briefing_service.py) | [docs/U03_DAILY_BRIEFING_ACCEPTANCE.md](../docs/U03_DAILY_BRIEFING_ACCEPTANCE.md) |
| U-04 | Owner-bound HTTP-only offline replay; account-switch rejection, retained failures and legacy quarantine | [app/static/js/offline_capture.js](../app/static/js/offline_capture.js); [app/api/routes/capture.py](../app/api/routes/capture.py) | [tests/test_offline_capture_ui.py](../tests/test_offline_capture_ui.py); [tests/test_offline_capture_owner.py](../tests/test_offline_capture_owner.py); [tests/extension/offline_capture_owner.test.mjs](../tests/extension/offline_capture_owner.test.mjs) | [docs/U04_OFFLINE_INGEST_QUEUE_ACCEPTANCE.md](../docs/U04_OFFLINE_INGEST_QUEUE_ACCEPTANCE.md) |
| G02 | Flat/hierarchical/fallback isolation; unambiguous vector tuples and canonical references | [app/db/vector_identity.py](../app/db/vector_identity.py); [app/services/search_service.py](../app/services/search_service.py) | [tests/test_vector_identity_acceptance.py](../tests/test_vector_identity_acceptance.py); [tests/test_postgres_search_service_acceptance.py](../tests/test_postgres_search_service_acceptance.py); [tests/test_postgres_connector_hierarchy_acceptance.py](../tests/test_postgres_connector_hierarchy_acceptance.py) | [docs/G02_RETRIEVAL_ISOLATION_ACCEPTANCE.md](../docs/G02_RETRIEVAL_ISOLATION_ACCEPTANCE.md) |
| V1-03 | Safe in-page YouTube metadata from current page | [extension/content.js](../extension/content.js) | [tests/extension/youtube_metadata_acceptance.test.mjs](../tests/extension/youtube_metadata_acceptance.test.mjs) | [docs/closeouts/V1_03_YOUTUBE_METADATA_CLOSEOUT.md](../docs/closeouts/V1_03_YOUTUBE_METADATA_CLOSEOUT.md) |
| V1-07 | Public repository save to shared connector pipeline | [app/services/sources/github_connector.py](../app/services/sources/github_connector.py) | [tests/test_universal_connectors.py](../tests/test_universal_connectors.py); [tests/extension/test_context.mjs](../tests/extension/test_context.mjs) | [docs/closeouts/V1_07_GITHUB_REPO_SAVE_CLOSEOUT.md](../docs/closeouts/V1_07_GITHUB_REPO_SAVE_CLOSEOUT.md) |
| V1-08 | Authenticated selected starred set, preview/confirm, secret-safe import | [app/services/github_starred_import_service.py](../app/services/github_starred_import_service.py) | [tests/test_github_starred_import.py](../tests/test_github_starred_import.py) | [docs/closeouts/V1_08_GITHUB_STARRED_IMPORT_CLOSEOUT.md](../docs/closeouts/V1_08_GITHUB_STARRED_IMPORT_CLOSEOUT.md) |
| V1-13 | Read-only evidence-only roadmap; missing topic never fabricates steps | [app/services/memory_intelligence_service.py](../app/services/memory_intelligence_service.py); [app/api/routes/intelligence.py](../app/api/routes/intelligence.py) | [tests/test_learning_path_acceptance.py](../tests/test_learning_path_acceptance.py); [tests/test_memory_intelligence.py](../tests/test_memory_intelligence.py) | [docs/V1_13_LEARNING_PATH_ACCEPTANCE.md](../docs/V1_13_LEARNING_PATH_ACCEPTANCE.md) |

The rest of F-01–F-38 and the release rows retain the existing G01–G28 ledger
contracts; they are not new credits. Auth/session ownership is covered by
`tests/test_v1_8_auth_privacy.py` and the production lifespan/fence suites.
Canonical record/provenance/lifecycle evidence remains in
`tests/test_universal_memory_service.py`, `tests/test_memory_lifecycle.py` and
G02's real vector reference resolution. P-03 migration/idempotency is exercised
by `tests/test_postgres_*migration*.py` and the account-fence migration replay test.
No unintended relational SQLite writes are permitted by the production lifespan,
combined privacy and connector hierarchy acceptance sentinels.

## Real gap found and closed: U-04 offline account-switch replay

Before this change, IndexedDB rows held only URL/time and replay used the current
browser credentials. Tenant A's queued private URL could therefore be imported
into tenant B after an account switch. Overlapping startup/online flushes could
also send the same row twice. The existing source-text tests did not prove these
behaviors. Three new Node behavioral tests fail against unchanged starting main.

The fix binds newly queued rows to an online-verified owner, retains credentials
only in the existing auth store/in-memory context, and replays only that owner's
rows. No credential is persisted in IndexedDB. A single in-flight flush prevents
overlapping replay. The API checks `X-Capture-Owner` against authenticated ownership
before constructing the capture service, covering a cookie-account switch between
identity lookup and write. The header never chooses the authenticated tenant.
Normal explicit capture remains backward compatible without this optional replay guard.

`tests/extension/offline_capture_owner.test.mjs` executes the actual browser module
with asynchronous IndexedDB/fetch fixtures: A cannot replay into B, B remains
writable, A can retry under a renewed A session, unverified identity fails closed,
failed writes retain rows, overlapping flushes do not duplicate writes, and queue
records contain no credentials. `tests/test_offline_capture_owner.py` exercises
the real FastAPI dependency/route boundary before the canonical capture service.
Existing Python UI source-contract tests remain intact.

Upgrade boundary: ownerless legacy rows are retained and never automatically
assigned to an account. They require explicit owner review/re-entry; this change
does not guess ownership or delete them. A page must establish its identity online
before accepting offline captures; a fresh offline page cannot verify an account.
This is an intentional fail-closed boundary, not a promise of offline authentication.

## Validation executed for this reconciliation

- New browser replay regression on unchanged starting-main module: **3 failed**,
  reproducing wrong-owner replay, missing identity check and concurrent duplication.
- Same behavioral regression with the repair: **3 passed**.
- Targeted API/offline/unified-command Python tests: **9 passed**.
- Mapped Python acceptance suites: **299 passed, 20 skipped** locally; the skipped
  PostgreSQL/Redis service cases require repository CI and are not claimed locally.
- Full extension helper suite: **30 passed**, including the three new behavioral regressions.
- Required full CI includes real PostgreSQL/Redis services, every Python test,
  extension helpers, version/manifest consistency and AHME benchmark.

## Historical, optional and external classification

| Suspicious statement / scope | Classification | Resolution / evidence |
|---|---|---|
| MASTER_SPEC "maturity today", F-12/16/23/27–30/32–35 Partial/Planned/Missing | Stale current text → CURRENT + COMPLETE | Current inventory corrected to the matrix contracts; no agent marketplace or enterprise-scale claim |
| MASTER_SPEC July test counts, V1 freeze, original gap proposals and phased roadmap | HISTORICAL/SUPERSEDED | Explicit history labels preserved; later closeouts supersede delivered tasks; no rewriting of old release decisions |
| CONNECTOR_SDK stub/catalog/unchecked acceptance | Stale current text → CURRENT + COMPLETE | Executable SourceConnector/registry/catalog and checklist added; original July proposal remains labeled history |
| SOURCE_OF_TRUTH old pending N/U rows and A-06/A-07 naming | HISTORICAL/SUPERSEDED | Current Gap/Consolidation catalog and every requested N/U row linked above; old document available in starting-main history |
| V1_PRODUCT_SPEC and capability matrix Missing/Partial | HISTORICAL/SUPERSEDED | Discovery-time audit explicitly labeled; V1_RELEASE_PLAN records completed in-repo phases |
| V1-03, V1-07, V1-08, V1-13 feature labels | Stale current text → CURRENT + COMPLETE | Dedicated code/regressions above; original phase column retained; starred provider setup remains external |
| C-09 native share, U-05 voice, generic autonomous marketplace, Jarvis interfaces | DEFERRED/JARVIS | Explicit FEATURE_IDEAS / AGENT_BIBLE boundaries; no completion credit |
| P-07 remote embeddings, graph-assisted retrieval enhancements, broader ontology | OPTIONAL | Existing deterministic/local acceptance does not require these extensions |
| V1-05 Watch Later production OAuth | EXTERNAL/HUMAN PREREQUISITE; deferred live path | V1-6 documented demo fallback; no scraping or fabricated provider approval |
| OAuth registration/consent, credentials, billing and live provider verification | EXTERNAL/HUMAN PREREQUISITE | C-02–C-07/V1-08 cover repository contracts, not live provider enrollment |
| Chrome Web Store publication, demo recording, public launch | EXTERNAL/HUMAN PREREQUISITE | G28 release materials already accepted; publication itself is not counted |
| Production migration/cutover, parity/rollback on a real legacy deployment, backup/WAL/replica purge | EXTERNAL/HUMAN PREREQUISITE | P-03 closeout explicitly separates implementation acceptance; no deployment/purge is inferred |

## Gate accounting and exact remaining boundary

The continuity sequence is P-03 → 23, U-03 → 24, G02/#382 → 25,
G15/#383 → 26, accepted N/U inventory/#384 → 27. This change earns exactly
one additional credit for the remaining historical/root-document reconciliation,
including closure of its discovered U-04 defect: **28/29**. It does not count those
features again, treat the already-complete G28 release row as new work, or reconstruct
the missing original 29-item mapping by summing candidate G-rows.

**Final 28→29 decision:** G29 is accepted by `docs/G29_FINAL_TRANSITION_CLOSEOUT.md`.
PR #385 exact head passed required CI #1357 (run `36207667005`), and GitHub compare
shows no file delta between that tested head and merged main `52feac7c4a3385bcd3cdfe55a907b3fbd5de2bd1`.
No reproducible covered isolation/privacy/retry defect remains open after the U-04
repair. External provider/deployment/human prerequisites remain outside this
repository-controlled transition decision. **Jarvis Gate: 29/29 cleared — 0 remaining.**

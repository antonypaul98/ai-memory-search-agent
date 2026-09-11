# P-03 remaining relational SQLite audit

Audit baseline: `e205873cccc8bd973dfed37c4b811540240e3b80` (PR #166), 2026-09-10. P-03 remains **Partial**.

## Method and boundary

Reviewed direct `sqlite3`, schema helpers, `migrate`, and `FTSIndex` imports across `app/`, their callers, backend selectors, and relevant tests. The table separates selected local implementations from runtime bypasses. It is a static call-path inventory, not a claim of complete dynamic zero-write proof. Chroma's own vector persistence is outside this relational SQLite retirement claim.

| Surface / implementation | Remaining behavior and required work |
| --- | --- |
| `app/main.py:lifespan`, `services/ingest_service.py:IngestService.__init__` | Unconditional schema migration can create/write SQLite even with Postgres stores selected. Remove only after dependent stores own their initialization and startup/profile tests prove safety. |
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

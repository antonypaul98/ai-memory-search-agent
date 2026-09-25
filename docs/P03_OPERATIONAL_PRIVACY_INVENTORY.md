# P-03 operational privacy inventory

> Historical P-03 evidence: code-level Partial/next-work statements below are
> superseded by the [2026-09-22 implementation closeout](P03_IMPLEMENTATION_CLOSEOUT_2026-09-22.md).
> Current gate accounting is in [JARVIS_GATE_LEDGER.md](JARVIS_GATE_LEDGER.md).

Audit date: 2026-09-15. Baseline: main `8e1cc8ab59ab59c6f2bff153829f75c04c26ab3f`
(#296). P-03 is **Partial**.

## Scope and evidence

Inspected all 52 literal `CREATE TABLE IF NOT EXISTS` declarations in
`app/db/postgres*.py`, selected-store routing, `PrivacyService`,
`delete_production_user_data`, and the public privacy routes. The table below
accounts for those declarations; it is a source audit, not proof of live schema
contents or complete production erasure. Dynamically generated schemas, external
services, filesystem payloads and future migrations require separate review.

Existing acceptance remains valid: #294 / CI #1123 exercises its combined
memory/feedback boundary under two live workers; #295 / CI #1125 supplies usage
primitives. #296 / CI #1127 passed 1,191 Python tests, 27 extension tests and the benchmark,
extending that acceptance to usage and failure/retry. A
successful bounded test does not clear unrelated rows below.

Classification: **portable** means user-owned data needing export treatment;
**derived** means regenerable data needing erasure/invalidation treatment;
**operational** means execution state needing a bounded lifecycle;
**security** means credentials or authorization state, never a raw export;
**system** means non-user control metadata. Classes can overlap. Calling data
operational or audit data does not itself justify indefinite retention.

## Relational inventory

Implementation paths below are relative to `app/db/` unless stated otherwise.
“Missing” refers to integration in the privacy lifecycle, not absence of any
standalone read/delete method.

| Tables | Classification and source | Current boundary / required follow-up |
| --- | --- | --- |
| `users`, `sessions` | Portable profile; security credentials. `postgres_auth_store.py` | Public profile export excludes password/session secrets. Session revocation exists, but production erasure does not revoke sessions or remove the user. Define an explicit account-erasure gate and prevent new writes before claiming account deletion. |
| `memory_records`, `memory_lifecycle_events`, `memory_versions`, `memory_trust_history` | Portable canonical data and provenance. `postgres_memory_store.py`, `memory_privacy.py` | Current-record export is capped at 10,000 and does not include all child history. Exact-memory deletion cascades history. Delete-all enumerates at most 50,000. Complete export/erasure needs pagination and history coverage. |
| `video_registry`, `video_reflection` | Portable saved-source metadata/reflection. `postgres_video_registry.py` | Registry export and per-memory deletion are wired. Audit reflection portability and rows without a canonical parent; canonical enumeration alone is insufficient for account erasure. |
| `youtube_memories` | Portable source records. `postgres_youtube_memory_store.py`, `selected_postgres_youtube_memory_store.py` | Export capped at 10,000; exact source/tenant deletion wired. Complete-account enumeration remains open. |
| `youtube_pipeline_runs`, `youtube_retry_queue`, `youtube_connector_metrics` | Operational history, retries and tenant metrics. `postgres_youtube_memory_store.py` | Not covered by PrivacyService export/erasure. Cancel/fence retries before cleanup; classify safe portable history and retention. Do not allow a retry to regenerate erased content. |
| `captures` | Portable capture and operational retry payload. `postgres_capture_store.py` | Export capped at 2,000 includes stored payload. No lifecycle erasure. Review credential redaction and remove retry payload only after cancellation/fencing. |
| `browser_bookmarks` | Portable bookmarks. `postgres_bookmark_store.py` | Export capped at 5,000; memory deletion does not delete imported bookmark rows. Complete export and explicit account erasure missing. |
| `import_runs`, `import_run_items` | Portable import history and operational work. `postgres_import_run_store.py` | Not included in privacy lifecycle. Parent deletion would cascade items; cancellation alone is not erasure. Fence running imports before deletion. |
| `content_url_index` | Derived deduplication identifiers. `postgres_content_url_index_store.py` | Exact memory reference deletion wired. Account-level cleanup of orphan rows remains required; never use hashes as ownership proof. |
| `ingest_artifacts` | Derived hashes and capsule content. `postgres_ingest_artifact_store.py`, `ingest_artifact_privacy.py` | Exact-tenant per-memory cleanup exists. Audit residual hash/orphan retention and canonical-source regeneration; raw derived export is not a replacement for portable canonical content. |
| `memory_fts_documents` | Derived lexical index. `postgres_fts_index.py` | Exact-tenant deletion occurs before canonical removal; shared-source neighbor preserved. Account-level orphan cleanup and migrated lexical parity remain acceptance boundaries. |
| `semantic_cache`, `cache_meta` | Derived private answers/questions; system version metadata. `postgres_semantic_cache_store.py` | Expiry filters reads; it does not erase expired rows. Per-tenant invalidate exists, but memory deletion bumps a global version and clears all cached tenants. Wire targeted account invalidation, including accounts with no canonical memories; keep system metadata outside personal export. |
| `memory_review_schedule` | Portable/derived review state. `postgres_review_schedule_store.py` | Tenant export and per-memory deletion wired. Verify orphan/account-level cleanup and complete enumeration. |
| `topic_profiles`, `topic_memory_links` | Portable/derived topic knowledge. `postgres_topic_store.py`, `topic_privacy.py` | Topic export capped at 500; per-memory links removed. Profiles remain. Explicit tenant cleanup and full export required. |
| `kg_entities`, `kg_relations`, `kg_memory_entities` | Portable graph facts and provenance. `postgres_knowledge_graph_store.py`, `knowledge_graph_privacy.py` | All three exported tenant-scoped. Memory deletion removes only memory/entity links; entities and relations remain. Erase exact-tenant graph content without deleting shared-source neighbors. |
| `concept_capsules`, `creator_profiles`, `learning_edges`, `intelligence_events` | Portable/derived intelligence and operational history. Corresponding `postgres_*_store.py` files | Not integrated into privacy export/erasure. Canonical tenant ownership must govern cleanup/regeneration. No indefinite-retention exception established. |
| `background_jobs`, `job_items`, `job_events`, `job_item_leases` | Portable job history and operational execution/leases. `postgres_runtime.py`, `postgres_job_claims.py` | Export lists at most 500 jobs, not a complete item/event/lease inventory. Erasure does not stop/remove jobs. Require worker fencing and late-finalization rejection before purging work. Parent ownership must govern children without tenant columns. |
| `memory_events`, `webhook_subscriptions` | Portable audit/activity and operational delivery configuration. `postgres_event_store.py` | EventBus privacy follow-up integrates complete event export with the existing payload redaction policy and subscription metadata (URLs excluded). Both tables are erased in one exact-tenant transaction with rollback/retry coverage. Already-dispatched deliveries and concurrent writers remain outside that transaction. No universal legal-retention exception inferred. |
| `agent_runs`, `agent_tool_calls` | Portable task/result history and operational execution. `postgres_agent_runtime_store.py` | Missing export/erasure; arguments/results may contain private content. Fence execution and validate both parent and child ownership before cascades. |
| `ingest_agent_rules`, `ingest_agent_claims` | Portable preferences and operational dedup/claims. `postgres_ingest_agent_store.py` | Disable/release operations exist; full export/erasure missing. Disable ingestion before cleanup; preserve explicit approval semantics. |
| `connector_oauth_tokens` | Security secrets plus portable non-secret consent metadata. `postgres_oauth_token_store.py` | Vault revocation exists; account erasure does not call it. Never export encrypted/decrypted token payloads. Provider-side revocation and in-flight connector work require explicit lifecycle handling. |
| `answer_interactions`, `answer_feedback`, `feedback_credit_ledger`, `output_preferences` | Portable feedback, preference and accounting data. `postgres_feedback_store.py`, `postgres_feedback_privacy.py` | Tenant export and transactional domain deletion integrated in #290/#292; #294 combined acceptance. No claimed legal/accounting retention exemption. |
| `model_route_usage` | Portable usage accounting. `postgres_model_usage_ledger.py`, `postgres_model_usage_privacy.py` | #295 primitives; #296 lifecycle integration and failure/retry acceptance. No prompts, credentials or provider requests are added by this slice. Concurrent-write prevention remains a broader account requirement. |
| `youtube_sqlite_migration_ledger` | Migration control/audit metadata. `postgres_youtube_memory_migration.py` | Keep separate from blind runtime deletion. Review tenant references and source fingerprints, retention and replay hazards; retained migration metadata must not authorize restoration of erased content. |
| `home_object_sightings`, `home_image_evidence`, `home_physical_objects`, `home_image_observations` | Existing portable/derived physical-memory data. `postgres_home_physical_memory_store.py`, `postgres_home_image_store.py` | Existing frame-delete behavior is separate from account privacy. Preserve existing foundation; no new Home features. If enabled in a deployment, account erasure must include relational and stored-image evidence; otherwise document the disabled scope explicitly. |

## Other boundaries and known limitations

- Chroma evidence/capsule/section vectors are separate from prohibited application
  relational SQLite. #284–#287 protect tenant-scoped deletion and legacy inventory.
  Account cleanup still needs orphan coverage. Never infer ownership of unscoped
  legacy vectors; retain preview-first, explicit confirmation and fail-closed reads.
- This inventory does not certify files, backups, Redis state, remote providers,
  webhook deliveries or optional provider data retention. Trace enabled production
  callers, TTLs, files and credentials before final acceptance.
- The public `/privacy/memories` endpoint deletes memories only. The internal
  production helper covers memory/feedback/model usage/activity, not the whole account;
  `deleted=true` describes those attempted domains. It is not connected to a
  separately confirmed account-erasure API.
- Live workers in #294/#296 poll successfully; their presence does not demonstrate
  safe deletion during active tenant ingestion. Account erasure requires an
  explicit durable write barrier and tests of late worker/provider completion.
- Table-level foreign keys do not universally encode composite tenant ownership.
  Test malformed child ownership before relying on cascade deletion as proof that
  another tenant cannot be deleted. Never repair ambiguity by assigning ownership.

## Next acceptance order

1. Validate/merge the EventBus privacy follow-up with exact-tenant, complete
   export and rollback coverage. Delivery URLs are explicitly excluded.
2. Address canonical export completeness and graph/intelligence residual data;
   then capture/import/job/agent/OAuth lifecycle integration. Keep each PR bounded.
3. Add confirmed account erasure with durable ingress/worker fencing, session
   revocation, safe retry and explicit coverage of all enabled domains. Preserve
   the separate memory-only API contract.
4. Reconcile remaining runtime/migration/parity tests and run final combined
   production acceptance before P-03 closure. Update this inventory as evidence
   changes. None of these rows automatically advances the historical gate count.

## Logical erasure versus deployment retention

SQL deletion proves logical row removal in the tested transaction boundary.
[PostgreSQL 16 routine vacuuming](https://www.postgresql.org/docs/16/routine-vacuuming.html)
explains MVCC row versions and later space reclamation. VACUUM is not a backup
purge guarantee. Operators must separately document backup/WAL retention,
replicas, physical purge and restoration policies that prevent resurrection.
No live migration, production credentials or infrastructure purge were used here.

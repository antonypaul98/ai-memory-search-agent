# P-03 — Production-wide Postgres migration

Status: **Partial**

P-03 is intentionally being completed in small, test-gated slices. SQLite remains the safe local/self-host default until the entire production profile and migration path are validated.

## Completed slices

- Durable job state / lease coordination can use Postgres.
- Auth and session persistence can explicitly use Postgres and fails closed when the environment-owned DSN is unavailable.
- Canonical universal memory records can explicitly use Postgres, including tenant identity, provenance, lifecycle events, version snapshots, trust snapshots/history, and deterministic tenant/source/external-id uniqueness.
- The tenant-scoped video/reflection/usage registry follows the Postgres production profile while preserving composite `(user_id, video_id)` identity.
- A first SQLite -> Postgres migration tool covers the video/reflection registry. It previews by default, requires explicit `--apply` for target writes, opens SQLite read-only, migrates in deterministic tenant/video order, and never overwrites an existing Postgres row on retry.
- Capture request/status state can explicitly use Postgres while preserving tenant-scoped reads, retries and updates.
- Safe capture-state migration tooling previews by default, requires explicit `--apply`, opens SQLite read-only, preserves the exact tenant and full request/status state, migrates in deterministic tenant/capture order, and never overwrites an existing Postgres capture row on retry.
- Browser bookmark synchronization state can explicitly use Postgres, preserving tenant/browser identity, complete-snapshot removal semantics, and partial-snapshot safety.
- Safe bookmark-state migration previews by default, requires explicit `--apply`, opens SQLite read-only, optionally scopes to one exact tenant, copies rows in deterministic tenant/browser/bookmark order, preserves sync/removal state, and never overwrites an existing `(user_id, browser_bookmark_id)` target row on retry.
- Import-run execution/history follows the Postgres bookmark production profile and keeps run/item reads, cancellation, updates, and history tenant-scoped. Safe import-run migration tooling is preview-first, source-read-only, deterministic, tenant-preserving, idempotent, and lets Postgres allocate target item IDs rather than copying SQLite autoincrement identities.
- A tenant-scoped Postgres full-text index primitive exists with composite `(user_id, doc_id)` identity, explicit tenant filters on every query/mutation, GIN-backed search documents, and deterministic score/doc-id ordering.
- Lexical retrieval has explicit `FTS_STORE_BACKEND=sqlite|postgres` selection and AHME forwards the resolved tenant identity to the selected index. The legacy SQLite FTS index remains available only for the unauthenticated local profile; authenticated SQLite lexical selection fails closed instead of risking an unscoped read.
- Ingestion resolves the lexical index through the same configured backend and forwards the resolved tenant identity on delete and every capsule/section/evidence upsert, so Postgres production ingestion cannot silently mutate the legacy unscoped SQLite FTS table.
- Safe lexical backfill tooling previews by default, requires explicit `--apply`, opens the SQLite source read-only, requires the operator to supply the exact tenant because the legacy FTS table has no tenant column, copies documents in deterministic order, and never overwrites an existing `(user_id, doc_id)` target row on retry.
- A read-only lexical retrieval-parity gate compares exact ordered document identities between the legacy SQLite source and tenant-scoped Postgres for an explicit operator-supplied query suite. It requires the exact tenant, returns a non-zero exit status on any identity/order mismatch, and never echoes query text or indexed content in its report.
- A tenant-scoped Postgres semantic-cache persistence primitive exists with composite `(user_id, cache_key)` identity, tenant-filtered exact/candidate reads and invalidation, deterministic candidate ordering, and Postgres-owned cache version metadata.
- Semantic-cache routing has explicit `SEMANTIC_CACHE_STORE_BACKEND=sqlite|postgres` selection. Reads, writes, tenant-scoped invalidation, aggregate stats, and memory-index version invalidation all use the selected backend together. Ingestion advances/invalidate the selected cache backend rather than calling SQLite cache metadata directly, preventing a Postgres cache profile from retaining hidden SQLite cache/version writes.
- Optional retained semantic-cache migration is preview-first and source-read-only. It preserves tenant identity, copies only rows compatible with the target cache versions, inserts in deterministic tenant/cache-key order, and uses `ON CONFLICT(user_id, cache_key) DO NOTHING` so retries never replace target-side cache state. Deployments may instead deliberately start with an empty Postgres cache because cache rows are disposable derived state.
- YouTube memories, pipeline/retry operational state, connector metrics, related reads, duplicate detection, retry completion, and ingestion can route through one fail-closed selected YouTube store. Safe legacy YouTube migration is preview-first, source-read-only, deterministic, tenant-aware, and refuses ambiguous attribution of legacy global connector metrics.
- Transcript hashes and serialized hierarchical capsule JSON now route through the same fail-closed YouTube backend selection. Postgres uses deterministic `(user_id, video_id)` identity and tenant-scoped unchanged checks; transcript and capsule fields update independently so one artifact write cannot erase the other.
- Safe ingest-artifact migration tooling and its ownership-proof hardening are CI-validated in PR #166. It requires explicit tenant selection because the legacy artifact tables have no tenant column, requires matching tenant-bearing YouTube/canonical source evidence for every artifact and rejects missing, invalid, contradictory or multi-tenant ownership before contacting Postgres, opens SQLite read-only, processes rows deterministically, previews by default, and only fills target fields that are still null so stale SQLite data cannot replace existing Postgres artifact values.
- Postgres credentials remain environment-owned via `POSTGRES_DSN_ENV`; no DSN or secret is persisted in application metadata or cache keys.

## Current configuration

- `AUTH_STORE_BACKEND=sqlite|postgres`
- `MEMORY_STORE_BACKEND=sqlite|postgres`
- `CAPTURE_STORE_BACKEND=sqlite|postgres`
- `BOOKMARK_STORE_BACKEND=sqlite|postgres`
- `FTS_STORE_BACKEND=sqlite|postgres`
- `SEMANTIC_CACHE_STORE_BACKEND=sqlite|postgres`
- `JOB_STORE_BACKEND=sqlite|postgres`
- `YOUTUBE_STORE_BACKEND=sqlite|postgres`
- `POSTGRES_DSN_ENV=DATABASE_URL`

Selecting Postgres is fail-closed. The application must not silently fall back to SQLite when a production store was explicitly requested. Authenticated lexical search additionally requires the tenant-scoped Postgres FTS backend because the historical SQLite FTS5 schema has no tenant column.

### Video/reflection migration

Preview counts without contacting Postgres:

```bash
python scripts/migrate_video_registry_to_postgres.py
```

Optionally scope the preview or migration to one exact tenant:

```bash
python scripts/migrate_video_registry_to_postgres.py --user-id <tenant-id>
```

Apply only after reviewing the preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_video_registry_to_postgres.py --apply
```

The command returns counts only; it does not print reflection text, URLs, credentials, or DSNs. Existing target rows are skipped rather than overwritten so a stale SQLite snapshot cannot clobber newer Postgres state.

### Capture migration

Preview capture counts without contacting Postgres:

```bash
python scripts/migrate_captures_to_postgres.py
```

Optionally scope the preview or migration to one exact tenant:

```bash
python scripts/migrate_captures_to_postgres.py --user-id <tenant-id>
```

Apply only after reviewing the count-only preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_captures_to_postgres.py --apply
```

The SQLite source is opened read-only. Capture rows are copied in deterministic tenant/capture order and existing `capture_id` rows are skipped rather than overwritten, so stale local state cannot replace target-side status, payload, or timestamps. Reports contain counts only; URLs, titles, payloads, errors, DSNs, and credentials are not printed.

### Bookmark migration

Preview bookmark counts without contacting Postgres:

```bash
python scripts/migrate_bookmarks_to_postgres.py
```

Optionally scope the preview or migration to one exact tenant:

```bash
python scripts/migrate_bookmarks_to_postgres.py --user-id <tenant-id>
```

Apply only after reviewing the count-only preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_bookmarks_to_postgres.py --apply
```

The source is opened read-only. Bookmark rows are copied in deterministic tenant/browser/bookmark order. Existing `(user_id, browser_bookmark_id)` rows are skipped rather than overwritten, preserving newer target-side state. Reports contain counts only; URLs, titles, DSNs, and credentials are not printed.

### Lexical migration

The legacy SQLite FTS5 table has no tenant identity, so ownership must never be guessed. Preview one local source only after supplying the exact tenant that owns it:

```bash
python scripts/migrate_fts_to_postgres.py --user-id <tenant-id>
```

After reviewing the count-only preview and provisioning the environment-owned Postgres DSN, explicitly apply:

```bash
python scripts/migrate_fts_to_postgres.py --user-id <tenant-id> --apply
```

The source is read-only. Existing Postgres rows are skipped with `ON CONFLICT(user_id, doc_id) DO NOTHING`, so retries cannot overwrite target-side documents produced after cutover.

### Ingest-artifact migration

Legacy transcript-hash and capsule tables have no tenant column. Preview only after selecting the exact tenant that owns the legacy source:

```bash
python scripts/migrate_ingest_artifacts_to_postgres.py --user-id <tenant-id>
```

After reviewing the count-only preview and provisioning the environment-owned Postgres DSN, explicitly apply:

```bash
python scripts/migrate_ingest_artifacts_to_postgres.py --user-id <tenant-id> --apply
```

Before any Postgres connection is opened, tenant-bearing `youtube_memories` and canonical YouTube `memory_records` evidence is checked. Every artifact must have exact, exclusive ownership proof from these records. Missing evidence (including absent ownership tables), null/blank/malformed tenant IDs, evidence for multiple tenants, or evidence contradicting the selected tenant aborts the whole migration. Operator selection alone is never ownership proof. Both artifact tables and ownership records are read within one read-only SQLite transaction; apply revalidates its own snapshot even after a preview. Source connections close on success and failure. Existing non-null target artifact fields remain authoritative; migration only fills missing fields. Reports contain counts and tenant identity only, never hashes, capsule JSON, URLs, DSNs, or credentials.

### Lexical retrieval parity

After migration, validate a representative acceptance query suite before enabling Postgres lexical search for that deployment:

```bash
python scripts/validate_fts_retrieval_parity.py \
  --user-id <tenant-id> \
  --query "first representative query" \
  --query "second representative query"
```

The validator is read-only. It compares exact ordered `doc_id` results and exits with status `2` when any query differs. Its JSON report contains only counts, tenant identity, query indexes, and document identities; it never echoes query text, snippets, titles, indexed bodies, DSNs, or credentials.

### Optional semantic-cache migration

Because semantic-cache rows are derived and disposable, the safest cutover is normally to start with an empty Postgres cache. If retained transfer is desired, preview source counts without contacting Postgres:

```bash
python scripts/migrate_semantic_cache_to_postgres.py
```

Optionally scope the preview or migration to one exact tenant:

```bash
python scripts/migrate_semantic_cache_to_postgres.py --user-id <tenant-id>
```

Apply only after reviewing the count-only preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_semantic_cache_to_postgres.py --apply
```

The source is opened read-only. Only rows whose index/preference versions match the target cache versions are eligible. Existing `(user_id, cache_key)` rows are skipped rather than overwritten, so stale derived state cannot replace target-side cache entries. Reports contain counts only; cached questions, answers, embeddings, DSNs, and credentials are not printed.

## Ingest-artifact acceptance evidence

PR #166, commit `99519a12af0af8d935c5336ca045ea5789754912`, passed [CI run 34494127491](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/34494127491): 791 Python tests with no skips, 27 extension tests, version consistency, and AHME benchmark smoke. `tests/test_postgres_ingest_artifact_migration_e2e.py` used the configured disposable Postgres service to prove whole-data-transaction rollback after hash writes, safe retries, preservation of existing target fields/timestamps, and isolation from another tenant with the same video ID. Schema provisioning remains a separate idempotent transaction.

`tests/test_postgres_ingest_artifact_migration.py` covers source ownership rejection before any target connection, one SQLite snapshot under concurrent writes, closed source handles on rejection, and CLI preview/apply revalidation. No live production data was migrated.

## Remaining before P-03 can be marked Complete

- Re-audit production code for remaining relational SQLite writes. Ingest-artifact migration ownership, retry, rollback and tenant-isolation acceptance passed real-Postgres CI in PR #166; this does not establish production-wide SQLite retirement.
- Run the lexical retrieval-parity gate against representative migrated state on a real Postgres service before enabling Postgres FTS for that migrated deployment.
- Add production-profile integration validation against a real Postgres service, including rollback/failure behavior and tenant-isolation checks.
- Prove the supported multi-worker production profile no longer depends on SQLite writes before SQLite can be retired from that profile.

## Safety boundary

This milestone does not change vector storage, enable autonomous writes, weaken confirmation gates, add mandatory AI, or begin Jarvis voice/vision/gesture/spatial/holographic work.

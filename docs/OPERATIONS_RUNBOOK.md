# Operations Runbook — AI Memory Search Agent

This runbook covers the supported single-node production profile for the Memory Search Agent. `MASTER_SPEC.md` remains the canonical feature/status source of truth.

## Supported deployment profile

- Python 3.11
- One FastAPI/Uvicorn process
- SQLite + FTS5 as relational/search metadata store
- Persistent ChromaDB on local disk
- Optional in-process background job worker
- Chrome extension + Workspace PWA clients

Do not run multiple Uvicorn workers against the same local SQLite/Chroma data directory. Horizontal scale is a later roadmap item.

## First-time setup

```bash
python3.11 -m venv .venv_clean
source .venv_clean/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

For local/demo use, the default settings are sufficient. For hosted use, review at minimum:

- `AUTH_ENABLED`
- `LOCAL_DEMO_MODE`
- `AUTH_SECRET`
- `JOBS_ENABLED`
- `RATE_LIMIT_ENABLED`
- `CORS_ORIGINS`
- `SQLITE_PATH`
- `CHROMA_PERSIST_DIR`
- `TRANSCRIPT_ARTIFACT_DIR`

Never commit real secrets to `.env.example` or the repository.

## Start the service

```bash
JOBS_ENABLED=true AUTH_ENABLED=false PWA_ENABLED=true \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Docker:

```bash
docker compose up --build
```

## Health checks

Use the split probes according to their purpose:

- `GET /api/v1/live` — process liveness. This should stay healthy even when dependencies are temporarily unavailable.
- `GET /api/v1/ready` — dependency-aware readiness. A failing Chroma dependency should make readiness fail.
- `GET /api/v1/health` — backward-compatible readiness alias.

The Docker health check uses `/api/v1/ready`.

## Observability

Every HTTP request receives an `X-Request-ID` response header. A valid caller-supplied request ID is propagated; unsafe values are replaced.

Request completion logs include request ID, method, path, status code, and duration. Process-local counters are exposed at:

```text
GET /api/v1/metrics
```

These metrics are intentionally lightweight and single-process. They are not a substitute for a distributed metrics backend at future scale.

## Run the test and benchmark gates

Before a release or merge to `main`:

```bash
source .venv_clean/bin/activate
pytest -q
```

AHME benchmark smoke:

```bash
BENCHMARK_RUNS=1 python scripts/benchmark_ahme.py
```

CI performs the same required validation on pull requests.

## Ingest one item from the CLI

```bash
python scripts/ingest_item.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Optional flags:

```bash
python scripts/ingest_item.py URL --force-refresh
python scripts/ingest_item.py URL --user-id local-default
```

The command prints structured JSON and returns a non-zero exit status on failure.

## Safely reset local data

Always preview first:

```bash
python scripts/reset_db.py --dry-run
```

Destructive reset requires explicit confirmation:

```bash
python scripts/reset_db.py --yes
```

The utility only targets configured Memory Search data paths and rejects unsafe broad filesystem targets.

## Legacy tenant metadata migration

Older Chroma rows created before strict tenant metadata may be missing `user_id`. Preview the migration:

```bash
python scripts/backfill_legacy_user_ids.py --dry-run
```

Apply it only after reviewing the preview:

```bash
python scripts/backfill_legacy_user_ids.py --yes
```

The migration is idempotent. It only assigns missing ownership to the historical `local-default` tenant, preserves existing vectors/documents/metadata, and does not modify already-owned rows.

## Backup

For the supported single-node profile, stop writes before taking a filesystem-level backup. Back up all configured persistent paths together so metadata and vectors remain consistent:

- SQLite database and sidecar files
- Chroma persistence directory
- Transcript artifact directory
- Any other configured local data directory used by the deployment

Example after stopping the service:

```bash
mkdir -p backups
cp -a data "backups/data-$(date +%Y%m%d-%H%M%S)"
```

Use your platform's snapshot/volume backup mechanism in hosted deployments.

## Restore

1. Stop the application and worker.
2. Move the damaged/current data directory aside; do not overwrite it immediately.
3. Restore SQLite, Chroma, and transcript artifacts from the same backup point.
4. Start the application.
5. Verify `/api/v1/ready`.
6. Run a known search and open at least one cited result.
7. Check background jobs before re-enabling normal ingest traffic.

## Common incident checks

### Application is running but readiness fails

1. Check `/api/v1/live`. If it succeeds, the process is alive.
2. Check `/api/v1/ready` and application logs.
3. Verify the Chroma persistence path exists and is writable.
4. Verify disk space and permissions.
5. Do not restart repeatedly if storage corruption is suspected; take a copy of the data directory first.

### Search returns no results for an authenticated user

1. Confirm the user identity/session.
2. Confirm memories were ingested under the same `user_id`.
3. If the data predates tenant metadata, run the legacy user-id migration in dry-run mode first.
4. Do not remove tenant filters to make results appear; isolation failures must fail closed.

### Background jobs are stuck

1. Confirm `JOBS_ENABLED=true` for the single-node all-in-one profile.
2. Inspect the job state through the job API/Workspace.
3. Retry only failed items rather than recreating the whole import when possible.
4. Avoid starting a second application worker against the same local database.

### High request volume or abuse

1. Keep `RATE_LIMIT_ENABLED=true` for hosted deployments.
2. Inspect `/api/v1/metrics` for status-code and request-count changes.
3. Reduce exposure or place the service behind a reverse proxy if necessary.
4. Do not disable request-size/SSRF protections to work around ingestion failures.

## Release checklist

Before declaring a Memory Search release candidate ready:

- Full `pytest -q` passes.
- AHME benchmark smoke completes.
- `/api/v1/live` and `/api/v1/ready` behave correctly.
- Auth/isolation regression tests are green.
- No secrets or real user data are present in the diff.
- `VERSION` matches `extension/manifest.json` when the extension version changes.
- README and `MASTER_SPEC.md` reflect material status changes.
- A backup/restore path has been verified for the deployment environment.

## Escalation boundaries

The current supported profile is intentionally single-node. The following are architectural transitions, not incident workarounds:

- multiple API/worker processes sharing local SQLite/Chroma
- distributed queue
- Postgres cutover
- managed vector database
- multi-region/high-availability operation

Those belong to later roadmap phases and should not be introduced ad hoc into the Phase 1 product.
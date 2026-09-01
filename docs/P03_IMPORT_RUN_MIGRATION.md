# P-03 — Import-run state migration

Status: **Implemented; real-Postgres execution still required before production cutover**

This slice provides safe SQLite -> Postgres transfer tooling for import execution/history and its item state.

## Safety contract

- Preview is the default. Postgres is not contacted unless `--apply` is supplied.
- The SQLite source is opened read-only and run/item rows are read inside one SQLite snapshot transaction.
- `--user-id` optionally scopes both run and item reads to one exact tenant; a blank tenant fails closed.
- Runs are processed deterministically by `(user_id, created_at, import_id)` and items by `(user_id, import_id, SQLite id)`.
- Existing Postgres `import_id` values are authoritative. A conflicting run and all of its source items are skipped as a unit; stale SQLite state never overwrites or partially merges into a newer target run.
- All run counters/status/detail/error/timestamps and all item URL/external-id/title/status/detail/error/capture/timestamps are preserved.
- SQLite item IDs are deliberately **not** copied. They are local surrogate keys, while Postgres owns a `BIGSERIAL` key. Letting Postgres allocate the target key prevents sequence corruption while preserving deterministic item order and business state.
- Reports expose counts only. They do not print URLs, titles, errors, connector payloads, DSNs, or credentials.

## Preview

```bash
python scripts/migrate_import_runs_to_postgres.py
```

Optional exact-tenant preview:

```bash
python scripts/migrate_import_runs_to_postgres.py --user-id <tenant-id>
```

## Apply

After reviewing the count-only preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_import_runs_to_postgres.py --apply
```

For one exact tenant:

```bash
python scripts/migrate_import_runs_to_postgres.py --user-id <tenant-id> --apply
```

Operationally quiesce import writers during the final migration/cutover. The source snapshot protects internal run/item consistency for one invocation, but it cannot prevent a separate process from writing newer SQLite state after that snapshot is taken.

## Validation still required

This implementation is not by itself proof that P-03 is production-complete. The broader P-03 gate still requires real-Postgres integration/rollback/tenant-isolation validation, representative lexical parity execution, auditing any remaining SQLite-backed production stores, and proof that the supported multi-worker production profile performs no SQLite writes.

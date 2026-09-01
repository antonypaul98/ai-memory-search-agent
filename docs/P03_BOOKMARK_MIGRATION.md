# P-03 Bookmark-state migration slice

Status: **implemented; pending exact-head CI and merge**

This slice adds safe SQLite -> Postgres transfer for `browser_bookmarks` while preserving the P-03 safety boundary.

## Guarantees

- Preview is the default; target writes require explicit `--apply`.
- SQLite is opened read-only and missing sources fail without creating a database.
- Optional `--user-id` scopes transfer to one exact tenant; blank tenant IDs fail closed.
- Rows are read deterministically by tenant, browser, and bookmark identity.
- Existing Postgres `(user_id, browser_bookmark_id)` rows are never overwritten, so stale local snapshots cannot clobber newer target state and retries are idempotent.
- Removal/sync state is preserved exactly rather than being re-derived during migration.
- Reports contain counts only and do not emit URLs, titles, DSNs, or credentials.

## Commands

Preview:

```bash
python scripts/migrate_bookmarks_to_postgres.py
```

Preview one tenant:

```bash
python scripts/migrate_bookmarks_to_postgres.py --user-id <tenant-id>
```

Apply only after reviewing the preview and provisioning the environment-owned Postgres DSN:

```bash
python scripts/migrate_bookmarks_to_postgres.py --apply
```

## Remaining P-03 transfer work

Import-run history/items still require their own safe migration slice. Real-Postgres integration/parity, failure/rollback validation, remaining relational-store audit, and zero-SQLite-write proof also remain before P-03 can be marked complete.

No Jarvis voice, vision, gesture, spatial, holographic, or ambient-capture work is included.

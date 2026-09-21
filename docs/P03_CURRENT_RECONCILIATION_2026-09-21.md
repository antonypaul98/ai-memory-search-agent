# P-03 current-main reconciliation — 2026-09-21

Status: **Partial — do not advance Jarvis Gate from 22/29 yet.**

This note reconciles the older P-03 privacy inventory against current `main` at `97d9a2a8a5846a97e41fef8de985f731e951bb6b`. It is intentionally narrow: it records later merged evidence so future acceptance work does not reimplement already-closed slices. The canonical final acceptance document remains `P03_FINAL_ACCEPTANCE_EVIDENCE.md` and must be updated when the remaining account-wide producer fence is proven.

## Later merged evidence that supersedes stale inventory rows

The 2026-09-15 operational inventory predates the following validated P-03 work now on `main`:

- durable account-erasure marker plus agent-runtime write fencing (`b98659c5c67679372aac396fb119176bcee90f41`);
- tenant import lifecycle erasure (#345 / `e8545cce1a8dfa8744bb85fa61be8e82c1ddd34d`);
- background-job lifecycle erasure and stale-worker heartbeat/finalization rejection (#347 / `dc8a9fb7de31e6a508c8dc103e9090e18109c793`);
- canonical-parent ownership for import and agent operational erasure (#350 / `ddec71fb3fc26a734b37a6bcfa50cd6c42fd8eee`);
- complete production privacy export enumeration and portable operational history (#351 / `20c106337e3729614328868cf947a3238168e615`).

These commits mean the old inventory statements that agent history, import lifecycle, background jobs, and complete export are wholly missing are no longer current. Preserve these implementations and their acceptance tests.

## Current implementation boundary

The durable marker is created before production erasure and the agent runtime consults it before creating or advancing agent work. Background-job deletion occurs after the durable fence; the real-Postgres job acceptance proves a deleted tenant's stale worker cannot heartbeat or complete its removed job while a neighboring tenant remains intact.

That evidence is necessary but not yet sufficient to claim an **account-wide write barrier**. P-03 closure still requires evidence that every enabled producer/ingress path that can recreate tenant-owned state after confirmed erasure either:

1. consults the durable account-erasure fence before accepting/committing new work, or
2. is durably cancelled/removed such that late completion cannot recreate state, or
3. is explicitly disabled/out of the production profile and documented as such.

Do not infer this from the existence of the marker alone. In particular, final acceptance must inventory enabled capture/ingest/connector/retry/background producer entry points and prove fail-closed behavior for the erased tenant while preserving a neighboring tenant.

## Required closure sequence

1. Trace every enabled production producer/ingress path from request/claim through persistence.
2. For each path, classify the current fence as `PASS`, `REAL CODE GAP`, or `DISABLED/OPERATOR SCOPE` with code/test evidence.
3. Add the smallest missing fence(s) and two-tenant regression coverage. Prefer real Postgres where the lifecycle is relational.
4. Run combined production acceptance on the exact PR head and then on merged `main` as required by repository policy.
5. Reconcile `P03_OPERATIONAL_PRIVACY_INVENTORY.md` and `P03_FINAL_ACCEPTANCE_EVIDENCE.md` so stale pre-#345/#347/#350/#351 statements no longer drive duplicate work.
6. Advance 22/29 to 23/29 only if the canonical gate definition permits deployment-only cutover prerequisites to remain explicitly external and every code-level acceptance requirement is green.

## Deployment boundary

No CI result can prove a live legacy deployment was migrated. Preview-first migration/cutover, representative lexical parity, rollback/readiness, backup/WAL/replica retention, and any environment-specific purge remain operator/deployment evidence when a live deployment exists. If no live legacy deployment exists, record that fact rather than fabricating a migration.

**Jarvis Gate: 22/29 cleared — 7 remaining.**

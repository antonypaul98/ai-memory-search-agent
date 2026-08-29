# Runtime Platform Closeout

This closeout records validated implementation evidence for roadmap items whose source-of-truth status text predates the current codebase. It exists to prevent duplicate rebuilds while the larger roadmap documents are reconciled.

## P-01 — Readiness vs liveness probes

Status: **Complete**

Evidence:

- `GET /api/v1/live` is a process-only liveness probe and does not perform heavyweight dependency checks.
- `GET /api/v1/ready` performs dependency readiness through `HealthService` and returns 503 when required storage is unavailable.
- `GET /api/v1/health` remains a backward-compatible readiness alias.
- Existing health-route tests and the full CI suite cover the behavior.

Acceptance result: deployment tooling can distinguish process liveness from dependency readiness without changing the legacy health contract.

## P-04 — Structured runtime metrics baseline

Status: **Complete for the current single-node Memory Search runtime**

Evidence:

- `GET /api/v1/metrics` exposes bounded process-local HTTP counters through `app.middleware.observability.metrics_snapshot`.
- The implementation is intentionally local-process scoped; it does not claim cross-process aggregation or a managed observability backend.

Acceptance result: the repository has an explicit metrics endpoint suitable for the current deployment profile. Future Prometheus exposition/aggregation is an enhancement, not a missing baseline.

## F-34 — Domain event bus / audit foundation

Status: **Complete for the Memory Search platform foundation**

Evidence:

- `app.services.event_bus.EventBus` is used by the agent runtime and other platform flows to persist tenant-scoped domain/audit events.
- Agent runs emit start, approval, tool-start, completion, and failure events.
- Tenant isolation and durable event retrieval are covered by automated tests such as `tests/test_agent_runtime.py` and event API/service coverage.

Acceptance result: important domain actions have a durable, tenant-scoped audit/event substrate. This does not imply every future Jarvis action type has been added.

## F-35 / P-08 — Distributed durable job runtime

Status: **Complete for the validated Postgres + Redis Memory Search runtime**

Evidence:

- Postgres is the durable job source of truth for split-process mode.
- Redis is used only as an opaque wake signal; job/user/content identifiers are not placed in the queue payload.
- Worker claims, leases, heartbeat ownership, stale-worker rejection, completion, and tenant-scoped reads are authoritative in Postgres.
- SQLite + split Redis remains fail-closed.
- CI validates the distributed path against real PostgreSQL and Redis service containers.

Acceptance result: the covered job behavior is safe for the repository's validated split API/worker profile. Future horizontal-scale tuning does not reopen the correctness milestone.

## Scope boundary

This closeout is limited to Memory Search platform work. It does not start or authorize Jarvis-specific voice, vision, gesture, spatial, hologram, or hardware features.

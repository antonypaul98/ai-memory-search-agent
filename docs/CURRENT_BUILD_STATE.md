# Current Memory Search Build State

Updated: 2026-08-28

This file records the implementation state used during the active Memory Search completion pass. `MASTER_SPEC.md` remains the canonical feature inventory; this document exists to prevent implementation/documentation drift while that larger inventory is reconciled.

## Completed in the current hardening pass

### F-34 — Event Bus & Observability

Status: **Complete for the documented F-34 / GAP-04 event-and-webhook scope.**

Implemented and validated behavior includes:

- durable tenant-scoped domain events and request correlation;
- privacy-safe event payloads with recursive credential redaction;
- producer coverage for ingest, delete, search, chat, API-driven job state changes, and authoritative worker item finalization;
- metrics/event-list APIs;
- durable tenant-scoped webhook subscriptions;
- explicit confirmation before enabling external webhook delivery;
- event-type filtering and wildcard subscriptions;
- SSRF validation plus DNS revalidation immediately before delivery;
- no redirect following for webhook delivery;
- webhook failure isolation so observability cannot roll back an already committed Memory Search operation;
- outbound webhook bodies omit tenant identifiers and private Memory Search content.

Relevant merged PRs: #55, #56, #57, #58, #59.

## Next required Memory Search work

Per the implementation order in `MASTER_SPEC.md`, the next feature remains **F-35 — Distributed Job Queue**, with **GAP-02 — SQLite as System of Record** as the blocking production-scale dependency.

Current F-35 foundation already includes:

- split API/worker runtime roles;
- stale item-claim recovery and leases;
- Redis wake transport using consumer-group streams;
- a fail-closed topology guard preventing split Redis workers from being presented as horizontally safe while durable job state is still SQLite-backed.

F-35 must **not** be marked complete until the durable relational claim/job state can safely support horizontal workers. The next implementation slice should therefore follow GAP-02's migration plan: introduce the smallest production-safe Postgres/SQLAlchemy persistence seam while preserving current SQLite single-node compatibility and deterministic claim semantics.

## Jarvis transition gate

Jarvis-specific voice, vision, gesture, spatial, hologram, or other future physical-interface work remains out of scope. Transition is permitted only after every planned Memory Search version and acceptance criterion is complete, stable, and validated with no known reproducible defect in covered behavior.

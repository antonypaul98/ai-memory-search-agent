# A-07 Consolidation Agent Closeout

Updated: 2026-08-29

## Canonical contract

`AGENT_BIBLE.md` defines the Consolidation Agent as deterministic maintenance that proposes duplicate-entity merges and stale-memory candidates. Writes must remain pending until explicit user approval; the acceptance criterion is that no merge occurs automatically.

## Validated implementation

- `ConsolidationAgent.analyze()` is read-only and tenant-scoped.
- Duplicate candidates are deterministic: only same-type non-memory entities whose names normalize to the same alphanumeric identity are proposed.
- Stale candidates are derived from persisted trust freshness and retain source/trust evidence in the response.
- Analysis returns `writes_performed=0` and never calls the entity merge service, changes lifecycle state, or mutates trust.
- A proposed entity merge is applied through `POST /api/v1/agents/consolidation/approve-merge` only when the authenticated user submits `confirm: true`.
- The approval boundary reuses the existing `EntityMergeService`; it does not create a second graph mutation implementation.
- `EntityMergeService` remains tenant-scoped, same-entity-type only, and rejects memory-entity merges.

## Regression evidence

`tests/test_consolidation_agent.py` proves:

1. analysis proposes a deterministic same-type duplicate while both graph entities remain unchanged;
2. cross-type and cross-tenant candidates are not proposed;
3. stale-memory suggestions cannot leak another tenant's memories;
4. authenticated analysis is tenant-scoped;
5. omitting `confirm` or sending `confirm: false` cannot perform a merge;
6. `confirm: true` performs exactly the requested approved merge;
7. even an explicitly confirmed request cannot merge a source entity from another tenant.

Existing `tests/test_entity_merge.py` separately covers graph rewiring, alias/provenance preservation, relation collapse, tenant isolation, type safety, and memory-entity rejection.

## Safety boundary

The Consolidation Agent does not autonomously execute suggestions. There is no background merge path and no mandatory LLM call. A merge remains a proposal until an authenticated explicit confirmation request crosses the approval boundary.

## Acceptance status

A-07 Consolidation Agent: **implementation and regression acceptance complete; full repository CI required before milestone merge/closure**.

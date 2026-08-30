# Current Memory Search Build State

Updated: 2026-08-30

This file records the implementation state used during the active Memory Search completion pass. `MASTER_SPEC.md` remains the canonical feature inventory; this document exists to prevent implementation/documentation drift while that larger inventory is reconciled.

## Validated platform foundation

The production/runtime foundation is now validated for the currently documented scope:

- readiness/liveness and the current observability baseline;
- durable tenant-scoped Event Bus, audit events, request correlation, privacy-safe webhook delivery, and recursive credential redaction;
- SQLite compatibility for local/single-node operation;
- Postgres durable job state with atomic claims/leases and tenant-safe controls;
- Redis consumer-group wake transport carrying opaque job wake markers only;
- fail-closed protection against split-worker SQLite deployments.

## Validated Memory Search closeouts

Recent acceptance closeouts include:

- F-12 grounded answer synthesis;
- F-16 optional, on-demand LLM providers with deterministic fallback;
- F-23 opt-in bookmark re-import;
- F-29 Connector SDK contract;
- F-30 SQLite registry client;
- N-02 claim/evidence verification;
- A-01 deterministic agent runtime with tenant isolation and approval gates;
- A-02 approved deterministic ingest-agent rules with canonical deduplication;
- A-03 bounded three-hop research with at least three distinct cited saved-memory sources;
- A-04 spaced Review Agent queue for active-goal memories stale for 14+ days;
- A-05 deterministic Capture Triage with canonical queue deduplication, tenant-scoped existing-memory checks, explicit junk/unsafe URL rejection, and full CI validation;
- A-06 deterministic Gap Agent analysis with evidence-backed actions, tenant isolation, explicit zero-memory goal handling, a per-goal actionable notification contract, and full CI validation;
- A-07 deterministic Consolidation Agent analysis remains read-only and tenant-scoped, and its entity-merge write boundary requires authenticated explicit `confirm: true` before reusing the existing tenant-safe merge service;
- N-01 deterministic Consensus Engine preserves explicit cross-source conflicts, computes source-backed agreement weight, avoids false source independence, and exposes consensus status/weight/source count plus both conflict sides in the Ask workspace;
- N-04 Gap Engine grounds missing-knowledge findings in observable coverage, source diversity, and review state rather than inventing unsupported curriculum topics;
- N-06 Reverse Memory deterministically turns grounded goal gaps into next-learning actions without mandatory AI;
- N-07 Learning Evolution uses bounded tenant-local feedback to evolve ranking without re-ingest or mutation of evidence scores.

N-04, N-06, and N-07 were carried together by the validated stacked PR #93 after CI run #656 passed and were squash-merged into `main` as commit `277063394e95da6b47d25a7d0d7d68064598b848`.

The implementation also already contains trust, duplicate merge, connectors, exports, and agent activity surfaces. Their canonical acceptance status must continue to be audited against executable tests before broad milestone closure.

## Current validation gate: F-33 Knowledge Graph & Entity Intelligence

`MASTER_SPEC.md` marks F-33 Partial and defines the remaining acceptance criteria as temporal facts and a cross-source entity merge UI.

The temporal portion is already implemented and regression-covered: graph relations support `valid_from` / `valid_to`, authenticated relation and neighbor queries accept an `at` timestamp, future/expired facts are filtered deterministically, and invalid timestamps are rejected.

The deterministic `EntityMergeService` already rewires memory links and graph relations, preserves aliases and merge provenance, collapses duplicate relations while keeping strongest confidence/evidence metadata, rejects memory-entity merges, enforces same-type entities, and remains tenant-scoped.

The remaining UI/safety boundary is being closed in `f33-knowledge-graph-closeout`: the Topics workspace exposes an Entity Merge Review surface that lists tenant-visible non-memory entities, limits candidates to the same entity type, requires visible user confirmation, and submits literal `confirm: true`. The generic entity-merge API now also requires literal `confirm: true`, so omitted or false confirmation cannot mutate the graph.

Regression coverage includes the existing temporal/merge suites plus `tests/test_entity_merge_ui.py` and an API confirmation-gate regression in `tests/test_entity_merge.py`.

Closeout candidate: `docs/closeouts/F33_KNOWLEDGE_GRAPH_CLOSEOUT.md`.

Do **not** mark F-33 complete until the full repository CI workflow passes on the PR containing this closeout candidate.

## Next required Memory Search work

First validate F-33. If CI fails, fix the failure with a regression test before continuing. If CI passes, merge through the normal safe GitHub boundary and then reconcile F-33 plus the already-validated N-04/N-06/N-07 rows in the root source-of-truth documents.

Continue the broader source-of-truth reconciliation across `MASTER_SPEC.md`, `FEATURE_IDEAS.md`, `CONNECTOR_SDK.md`, `KNOWLEDGE_ENGINE.md`, `AGENT_BIBLE.md`, and `README.md`, correcting only rows whose acceptance behavior is backed by implementation and tests. Do not infer completion merely from the presence of a service or API.

Known documentation drift to resolve during that reconciliation:

- `FEATURE_IDEAS.md` still marks already validated F-12, F-16, F-23, F-30, N-01, N-02, N-04, N-06, N-07, and A-01–A-07 work as Partial/Planned/Missing;
- `FEATURE_IDEAS.md` uses the old A-06/A-07 Policy/Guardrails and Agent Audit UI labels, while `AGENT_BIBLE.md` and the validated implementation define the active A-06/A-07 closeouts as Gap and Consolidation Agents;
- `MASTER_SPEC.md` and `KNOWLEDGE_ENGINE.md` still describe consensus/agents/scale-out capabilities as planned even where executable implementation now exists;
- several connector, graph, Postgres/Redis, export, trust, cross-source-dedup, and other knowledge-intelligence rows appear stale and must be audited individually rather than mass-marked complete.

Graph / connector / platform / trust / export rows must each be evaluated against their exact documented acceptance criteria and tenant/privacy/provenance requirements. Run the final Memory Search acceptance/stability gate only after every planned item is reconciled.

No Jarvis transition is permitted merely because the agent catalog or knowledge-engine implementations exist.

## Jarvis transition gate

Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, or physical-interface work remains out of scope. Transition is permitted only after every planned Memory Search version and acceptance criterion is complete, stable, and validated with no known reproducible defect in covered behavior.

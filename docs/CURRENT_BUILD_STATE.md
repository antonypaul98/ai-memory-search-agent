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
- A-07 deterministic Consolidation Agent analysis remains read-only and tenant-scoped, and its entity-merge write boundary requires authenticated explicit `confirm: true` before reusing the existing tenant-safe merge service; PR #88 passed full CI and was merged into `main`;
- N-01 deterministic Consensus Engine preserves explicit cross-source conflicts, computes source-backed agreement weight, avoids false source independence, and exposes consensus status/weight/source count plus both conflict sides in the Ask workspace. Its dedicated acceptance regression passed the full repository CI gate in PR #89 and was merged into `main`.

The N-01 follow-up source-of-truth bookkeeping in PR #90 also passed CI and was merged into `main` before the next acceptance audit began.

N-06 Reverse Memory has full repository validation evidence: PR #91 CI run #654 passed on the exact explicit-goal acceptance regression. N-07 Learning Evolution also passed the full repository CI gate in PR #92 CI run #655, including the regression proving tenant-local feedback can change ranking without re-ingest or evidence-score mutation. The available GitHub connector still blocks the irreversible merge action, so do not represent N-06 or N-07 as merged until a normal safe merge succeeds.

The implementation also already contains trust, duplicate merge, connectors, exports, and agent activity surfaces. Their canonical acceptance status must continue to be audited against executable tests before broad milestone closure.

## Current validation gate: N-04 Gap Engine

`FEATURE_IDEAS.md` defines N-04 as detecting knowledge holes relative to a stated goal (summarized as “you wanted X but never saved Y”), and `KNOWLEDGE_ENGINE.md` describes it as detecting holes in memory relative to goals.

The existing deterministic `GapAgent` already analyzes authenticated tenant-local reflection goals, includes explicitly requested goals even when they have zero memories, reports evidence-backed coverage/source-diversity/review gaps, and emits one actionable notification per gap-bearing goal. It performs no network fetch, autonomous memory write, or mandatory LLM call.

The repository does not currently define a curriculum or ontology from which an arbitrary missing subtopic `Y` could be inferred safely. The Gap Engine therefore does not invent missing topics; it grounds gap findings in observable coverage, source diversity, and review state. Reverse Memory N-06 turns those grounded findings into next-learning actions.

Existing regression coverage in `tests/test_gap_agent.py` directly proves zero-memory explicit goals, well-covered suppression, evidence-backed stale/single-source gaps, tenant isolation, and authenticated API scoping.

Closeout candidate: `docs/closeouts/N04_GAP_ENGINE_CLOSEOUT.md`.

Do **not** mark N-04 complete until the full repository CI workflow passes on the PR containing this closeout candidate.

## Next required Memory Search work

First validate the N-04 Gap Engine closeout candidate. If CI fails, fix the failure with a regression test while preserving deterministic tenant-scoped evidence and zero autonomous writes. If CI passes, reconcile the stale N-04/N-06/N-07 status rows in `KNOWLEDGE_ENGINE.md` and `FEATURE_IDEAS.md`, then continue to the next remaining Memory Search acceptance item.

Retry the already-green N-06/N-07 merge only through the normal safe GitHub merge boundary; do not bypass connector safety checks.

Continue the broader source-of-truth reconciliation across `MASTER_SPEC.md`, `FEATURE_IDEAS.md`, `CONNECTOR_SDK.md`, `KNOWLEDGE_ENGINE.md`, `AGENT_BIBLE.md`, and `README.md`, correcting only rows whose acceptance behavior is backed by implementation and tests. Do not infer completion merely from the presence of a service or API.

Known documentation drift to resolve during that reconciliation:

- `FEATURE_IDEAS.md` still marks already validated F-12, F-16, F-23, F-30, N-01, N-02, N-06, N-07, and A-01–A-07 work as Partial/Planned/Missing;
- `FEATURE_IDEAS.md` uses the old A-06/A-07 Policy/Guardrails and Agent Audit UI labels, while `AGENT_BIBLE.md` and the validated implementation define the active A-06/A-07 closeouts as Gap and Consolidation Agents;
- `MASTER_SPEC.md` and `KNOWLEDGE_ENGINE.md` still describe consensus/agents/scale-out capabilities as planned even where executable implementation now exists;
- several connector, graph, Postgres/Redis, export, trust, cross-source-dedup, and other knowledge-intelligence rows appear stale and must be audited individually rather than mass-marked complete.

Graph / connector / platform / trust / export rows must each be evaluated against their exact documented acceptance criteria and tenant/privacy/provenance requirements. Run the final Memory Search acceptance/stability gate only after every planned item is reconciled.

No Jarvis transition is permitted merely because the agent catalog or knowledge-engine implementations exist.

## Jarvis transition gate

Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, or physical-interface work remains out of scope. Transition is permitted only after every planned Memory Search version and acceptance criterion is complete, stable, and validated with no known reproducible defect in covered behavior.

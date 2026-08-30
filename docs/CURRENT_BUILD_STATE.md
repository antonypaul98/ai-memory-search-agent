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

N-06 Reverse Memory now has full repository validation evidence: PR #91 CI run #654 passed on the exact explicit-goal acceptance regression. The merge mutation is still pending because the available GitHub connector blocked that irreversible action at its safety boundary. Do not represent N-06 as merged until that action succeeds.

The implementation also already contains trust, learning evolution, duplicate merge, connectors, exports, and agent activity surfaces. Their canonical acceptance status must continue to be audited against executable tests before broad milestone closure.

## Current validation gate: N-07 Learning Evolution

`KNOWLEDGE_ENGINE.md` defines N-07 as memory improving over time from usage without full re-ingest. `FEATURE_IDEAS.md` summarizes its acceptance target as re-ranking/re-summarizing without full re-ingest.

The existing implementation derives a small deterministic ranking adjustment from tenant-local helpful/not-helpful feedback and views. Explicit feedback is bounded, views have weaker influence, search counts are excluded to prevent self-reinforcement, and learning metadata failure cannot break core retrieval. The original relevance/similarity evidence score remains unchanged for auditability.

A dedicated acceptance regression now searches the same already-indexed results before and after later helpful feedback. It requires the ordering to evolve only after the tenant-local usage signal changes while preserving the original evidence score and performing no repository/memory write.

Closeout candidate: `docs/closeouts/N07_LEARNING_EVOLUTION_CLOSEOUT.md`.

Do **not** mark N-07 complete until the full repository CI workflow passes on the PR containing this acceptance regression.

## Next required Memory Search work

First validate the N-07 Learning Evolution acceptance candidate. If CI fails, fix the failure while preserving deterministic bounded learning, tenant isolation, evidence auditability, and fail-open retrieval. If CI passes, mark N-07 validated, reconcile its stale `KNOWLEDGE_ENGINE.md`/inventory status, and continue to the next remaining Memory Search acceptance item.

Retry the already-green N-06 PR #91 merge only through the normal safe GitHub merge boundary; do not bypass connector safety checks. Because that merge remains blocked, PR #92 is temporarily retargeted to `main` so the repository CI gate can validate the combined, already-green N-06 changes together with the new N-07 acceptance regression. This is a validation path only: do not claim N-06 or N-07 merged unless a normal merge action actually succeeds.

Continue the broader source-of-truth reconciliation across `MASTER_SPEC.md`, `FEATURE_IDEAS.md`, `CONNECTOR_SDK.md`, `KNOWLEDGE_ENGINE.md`, `AGENT_BIBLE.md`, and `README.md`, correcting only rows whose acceptance behavior is backed by implementation and tests. Do not infer completion merely from the presence of a service or API.

Known documentation drift to resolve during that reconciliation:

- `FEATURE_IDEAS.md` still marks already validated F-12, F-16, F-23, F-30, N-01, N-02, and A-01–A-07 work as Partial/Planned/Missing;
- `FEATURE_IDEAS.md` uses the old A-06/A-07 Policy/Guardrails and Agent Audit UI labels, while `AGENT_BIBLE.md` and the validated implementation define the active A-06/A-07 closeouts as Gap and Consolidation Agents;
- `MASTER_SPEC.md` and `KNOWLEDGE_ENGINE.md` still describe consensus/agents/scale-out capabilities as planned even where executable implementation now exists;
- several connector, graph, Postgres/Redis, export, Reverse Memory, learning-evolution, and other knowledge-intelligence rows appear stale and must be audited individually rather than mass-marked complete.

Reverse Memory / learning evolution / graph / connector / platform rows must each be evaluated against their exact documented acceptance criteria and tenant/privacy/provenance requirements. Run the final Memory Search acceptance/stability gate only after every planned item is reconciled.

No Jarvis transition is permitted merely because the agent catalog, N-01 consensus work, N-06 validation, or N-07 candidate implementation exists.

## Jarvis transition gate

Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, or physical-interface work remains out of scope. Transition is permitted only after every planned Memory Search version and acceptance criterion is complete, stable, and validated with no known reproducible defect in covered behavior.

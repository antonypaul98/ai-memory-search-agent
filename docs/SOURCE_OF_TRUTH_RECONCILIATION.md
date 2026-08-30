# Memory Search Source-of-Truth Reconciliation

Updated: 2026-08-30

Purpose: provide a conservative bridge between validated executable behavior and stale architecture/backlog labels while the root documents are corrected. `MASTER_SPEC.md` remains the canonical feature inventory. This document must never be used to mark a feature complete merely because a service, route, or file exists.

## Reconciliation rule

A row may be promoted only when its documented acceptance behavior is backed by implementation plus automated tests that have passed repository CI. Optional future enhancements remain optional and do not get silently folded into the accepted contract.

## Validated rows whose root-document status is stale

The following rows already have CI-validated closeouts on `main` and should be reconciled in the root documents without expanding their acceptance scope:

- F-12 Grounded answer synthesis — deterministic grounded synthesis plus optional provider path with fallback.
- F-16 LLM provider — optional/on-demand provider integration with deterministic fallback; no mandatory AI.
- F-23 Bookmark import — explicit opt-in import/re-import behavior with preview/confirmation boundaries.
- F-29 Source/Connector framework — registry, normalized connector contract, provenance-preserving ingest path.
- F-30 SQLite registry client — tenant-scoped list/delete behavior without Chroma scan.
- F-33 Knowledge Graph & Entity Intelligence — tenant-scoped entities/relations, temporal facts, deterministic merge/dedup, visible Entity Merge Review UI, and literal `confirm: true` at the generic merge boundary.
- N-01 Consensus Engine — deterministic independent-source consensus, explicit disagreement preservation, visible weight/source count, no contradictory-claim collapse.
- N-02 Verification Engine — claim/evidence verification closeout already validated; future freshness/trust enhancements remain separate unless explicitly accepted.
- N-04 Gap Engine — evidence-backed coverage/source-diversity/review gaps; no invented curriculum topics.
- N-06 Reverse Memory — deterministic next-learning actions from grounded gaps without mandatory AI.
- N-07 Learning Evolution — bounded tenant-local feedback can re-rank already-indexed results without re-ingest or mutation of evidence scores.
- A-01 Agent Runtime — deterministic runtime, tenant isolation, typed tool execution, and approval gating.
- A-02 Ingest Agent — approved deterministic ingest rules with canonical deduplication.
- A-03 Research Agent — bounded multi-hop retrieval with at least three distinct cited saved-memory sources.
- A-04 Review Agent — active-goal review queue for memories stale for 14+ days.
- A-05 Capture Triage Agent — deterministic queue deduplication, existing-memory checks, SSRF/junk rejection, tenant isolation.
- A-06 Gap Agent — read-only deterministic gap analysis with actionable per-goal notification contract.
- A-07 Consolidation Agent — read-only deterministic proposals; entity merge writes require authenticated explicit confirmation and tenant-safe merge service reuse.

## Known naming drift

`FEATURE_IDEAS.md` still uses the older A-06/A-07 labels (`Policy / guardrails`, `Agent audit UI`). The validated agent catalog in `AGENT_BIBLE.md` and implementation uses:

- A-06 — Gap Agent
- A-07 — Consolidation Agent

The old labels must not be treated as separate missing features unless `MASTER_SPEC.md` explicitly promotes them under new IDs and acceptance criteria.

## Root documents requiring correction

### FEATURE_IDEAS.md

Reconcile the stale Partial/Planned/Missing statuses for the validated rows above. Preserve genuinely future enhancements such as OAuth-dependent connectors, distributed-scale work, optional trust ranking, and Jarvis-only UX.

### KNOWLEDGE_ENGINE.md

Reconcile N-01, N-02, N-04, N-06, N-07 and F-33 to their validated acceptance state. In particular, the document still says F-33 temporal facts and entity merge/dedup UI are missing although those paths are now validated on `main`.

### AGENT_BIBLE.md

Replace the global `no agents implemented` statement with the validated runtime/catalog state. A-01 through A-07 are implemented for their documented Memory Search acceptance boundaries. Future multi-agent orchestration, richer scheduling, external/network tools, or Jarvis UX remain future unless separately accepted.

### MASTER_SPEC.md

Reconcile maturity language that still describes agents, consensus/gap engines, Connector SDK, and scale-out foundations as planned where validated implementation now exists. Do not remove historical V1 freeze language; distinguish historical release gating from current implementation state.

### CONNECTOR_SDK.md and README.md

Audit wording against the validated connector framework and current product surface. Do not mark OAuth/provider-specific connectors complete unless their own acceptance tests exist.

## Still pending individual acceptance audit

The following areas must be checked separately rather than promoted from file presence:

- N-03 / F-38 trust UI/ranking/feedback boundaries beyond the already validated trust foundation;
- N-08 cross-source duplicate review/merge behavior if distinct from F-33 entity merge;
- C-02 and provider OAuth flows;
- C-03/C-04/C-05/C-06/C-07/C-08/C-09 connector/export/share-sheet rows against exact acceptance criteria;
- P-01/P-03/P-04/P-07/P-08 platform rows against current runtime/tests;
- F-34/F-35 event-bus/distributed-queue inventory wording against the already validated platform foundation;
- U-01/U-02/U-03/U-04 and any other Memory Search UX rows that are not Jarvis-specific;
- any remaining version/milestone acceptance criteria referenced by repository roadmaps.

## Jarvis transition gate

No Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, or physical-interface work is authorized by this reconciliation. Jarvis work begins only after every planned Memory Search item is reconciled, implemented where necessary, and passes the final acceptance/stability gate with no known reproducible defect in covered behavior.

# Memory Search Backlog Reconciliation — 2026-08-31

This closeout records repository-validated Memory Search capabilities whose root backlog labels remain stale after their implementation/acceptance PRs. It is intentionally limited to already-covered behavior and does not promote any Jarvis-specific scope.

## N-05 Knowledge Graph store — acceptance complete

Validated current boundary:

- tenant-scoped entity and relation persistence
- entity search and neighbor traversal
- temporal relation support
- evidence/provenance metadata retained on graph records
- authenticated query surfaces for entities, relations, neighbors, and memory-to-entity links
- graph merge writes remain explicitly confirmed and tenant checked
- no mandatory AI dependency

Acceptance closeout: `docs/closeouts/N05_KNOWLEDGE_GRAPH_STORE_CLOSEOUT.md`.

## N-08 Cross-source dedup UI — acceptance complete

Validated current boundary:

- duplicate candidates are surfaced to the user
- both memories can be inspected before action
- shared-topic/diversity evidence is presented
- merge direction resolves to canonical memory records
- no merge is executed without explicit confirmation
- tenant isolation and deterministic deduplication remain preserved

Acceptance closeout: `docs/closeouts/N08_CROSS_SOURCE_DEDUP_UI_CLOSEOUT.md`.

## U-06 Trust badges on results — current UI acceptance complete

Validated current boundary:

- persisted trust tier/score is rendered in the PWA search experience
- extension search results render the same persisted trust metadata
- display percentages are bounded and hostile labels are escaped
- missing/invalid trust metadata degrades safely
- rendering does not trigger AI calls or mutate trust/evidence state

This does **not** declare the broader N-03 Trust Engine roadmap complete. Richer consensus-weighted trust policy, additional trust-aware search controls, and future agent policy tiers remain separate work.

## Source-of-truth reconciliation note

`FEATURE_IDEAS.md` still contains stale labels for N-05, N-08, and U-06 at the time of this closeout. Those rows should be reconciled to the validated boundaries above before using the backlog as the next-feature selector.

After that reconciliation, genuine remaining Memory Search work includes, subject to `MASTER_SPEC.md` ordering and acceptance criteria: N-03 richer trust policy, P-03 production-wide Postgres migration, P-07 optional remote embeddings, U-01/U-02/U-04, and remaining incomplete V1 capability rows. Jarvis voice/vision/gesture/spatial/hologram work remains out of scope until the Memory Search completion gate is satisfied.

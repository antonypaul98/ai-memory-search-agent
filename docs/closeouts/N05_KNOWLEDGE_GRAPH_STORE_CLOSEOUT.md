# N-05 Knowledge Graph Store — Acceptance Closeout

Date: 2026-08-31

## Canonical acceptance

`FEATURE_IDEAS.md` defines N-05 as the Knowledge Graph store with the acceptance boundary **“Entities + relations queryable.”** This closeout records the repository-controlled implementation that already satisfies that boundary; it does not create a second graph subsystem or expand into Jarvis-specific behavior.

## Accepted implementation

- `KnowledgeGraphStore` persists tenant-scoped graph entities, relations, and memory links.
- `KnowledgeGraphService` exposes deterministic entity search, entity lookup, relation lookup, memory-to-entity lookup, and bounded neighbor traversal.
- `GET /knowledge/entities`, `GET /knowledge/entities/{entity_id}`, `GET /knowledge/entities/{entity_id}/relations`, `GET /knowledge/graph/neighbors`, and `GET /knowledge/memories/{memory_id}/entities` are authenticated and derive `user_id` from the current tenant rather than accepting an arbitrary tenant from the client.
- Relation records retain temporal validity plus confidence/evidence metadata where present.
- Ingest-time graph linking is already part of the accepted F-33 implementation.
- Cross-source entity merge remains deterministic, tenant-scoped, and explicitly confirmation-gated under the separate F-33 acceptance boundary.

## Regression evidence

`tests/test_knowledge_graph.py` covers:

- entity and relation creation from a canonical memory,
- memory-to-entity linkage,
- entity search,
- neighbor traversal,
- relation predicates,
- half-open temporal relation filtering,
- tenant-scoped relation mutation, and
- preservation of evidence metadata when closing relations.

Authenticated graph API behavior and temporal query regressions are additionally covered by the existing brain/temporal API suites referenced by the F-33 closeout.

## Safety and architecture invariants

- Tenant identity is enforced at the service/API boundary.
- Provenance/evidence metadata is preserved rather than synthesized.
- Graph queries and merges require no mandatory LLM call.
- No autonomous/destructive graph write is introduced by this closeout.
- Existing explicit confirmation gates for merge/rewiring operations remain unchanged.
- No voice, vision, gesture, spatial, hologram, ambient-capture, or hardware work is included.

## Scope boundary

N-05 does **not** require graph-powered AHME retrieval, a new graph database product, or Jarvis-scale orchestration. Those remain separate future enhancements unless explicitly promoted in the source-of-truth specifications.

## Validation gate

Mark N-05 acceptance-complete only after this branch passes the repository CI workflow. Root backlog labels that still say `Planned` should be reconciled after that validation so the source-of-truth documents match executable behavior.

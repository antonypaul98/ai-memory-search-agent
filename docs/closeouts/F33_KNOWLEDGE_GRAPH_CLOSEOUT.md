# F-33 Knowledge Graph & Entity Intelligence — Closeout Candidate

Date: 2026-08-30

## Canonical acceptance

`MASTER_SPEC.md` requires persisted tenant-scoped entities/relations, ingest-time memory linking, entity search and neighbor APIs, temporal facts, and a cross-source entity merge UI.

## Evidence in the implementation

- `KnowledgeGraphStore` / `KnowledgeGraphService` persist and query tenant-scoped graph entities, relations, and memory links.
- `tests/test_knowledge_graph.py` and `tests/test_brain_api.py` cover graph persistence and authenticated API behavior.
- `tests/test_temporal_knowledge_api.py` proves half-open `valid_from` / `valid_to` temporal filtering, historical neighbor queries, and rejection of invalid timestamps.
- `EntityMergeService` deterministically rewires memory links and relations, collapses duplicate relations while preserving the strongest confidence/evidence metadata, preserves aliases/merged IDs, rejects memory-entity merges, enforces same-type merges, and remains tenant-scoped.
- The Topics workspace now contains an Entity Merge Review surface. It lists tenant-visible non-memory entities, only offers same-type merge candidates, requires a visible `window.confirm`, and submits literal `confirm: true` to the authenticated merge endpoint.
- The generic graph merge API now also requires literal `confirm: true`; omitted or false confirmation is rejected before any mutation.

## Safety / product constraints

- No LLM is required for graph queries or merge execution.
- No cross-tenant entity is exposed or mergeable.
- Entity merge remains a user-approved write; no autonomous merge was introduced.
- Existing relation confidence, evidence metadata, aliases, and memory links are preserved by the deterministic merge service.
- No Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, or hardware behavior is included.

## Validation gate

Do not mark F-33 complete until the full repository CI workflow passes with the confirmation-gate and UI acceptance regressions included.

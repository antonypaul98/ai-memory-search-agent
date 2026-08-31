# V1-13 Learning Path Generator — Acceptance Closeout

**Status:** Acceptance candidate  
**Scope:** Memory Search Agent only; no Jarvis-specific behavior

## Acceptance boundary

V1-13 is satisfied by the existing Memory Intelligence roadmap capability rather than a second learning-path subsystem.

- `GET /api/v1/intelligence/roadmap?topic=...` is authenticated and forwards the current tenant identity to `MemoryIntelligenceService.roadmap()`.
- Paths are generated only from the tenant's saved topic evidence and saved memories.
- Steps are grouped into beginner, intermediate, and advanced levels using deterministic metadata/content cues already defined by V1-3.
- Recommended ordering is deterministic and evidence-backed; the response is explicitly marked `evidence_only=true`.
- Missing topics fail grounded: the API reports that no saved memories exist instead of inventing external videos, prerequisites, or claims.
- Learning-path generation is read-only. It does not mutate memories, merge records, ingest content, or bypass confirmation gates.
- No LLM is required for this capability; the deterministic path remains available without an AI provider.
- Existing canonical records, provenance/evidence, tenant isolation, and deterministic deduplication remain owned by the normal Memory ingestion and intelligence layers rather than being duplicated here.

## Existing implementation reused

- `app/api/routes/intelligence.py` — tenant-scoped `/intelligence/roadmap` route.
- `app/services/memory_intelligence_service.py` — deterministic `roadmap()` projection over saved topic/video evidence.
- `app/models/intelligence.py` — typed `LearningRoadmap` / `RoadmapStep` models with `evidence_only`.
- `tests/test_memory_intelligence.py` — existing learning-graph and roadmap behavior, ordering presence, and evidence-only regression coverage.
- `docs/V1_3_MEMORY_INTELLIGENCE.md` — original roadmap contract: saved memories only, deterministic level/order logic, no fabricated external videos.

## Added acceptance regressions

`tests/test_learning_path_acceptance.py` locks two safety-critical behaviors:

1. A topic with no saved evidence returns an explicit missing-memory gap and zero fabricated steps.
2. The HTTP API forwards only the authenticated tenant ID to the roadmap service.

## Explicitly out of scope

This closeout does **not** add autonomous course generation, external-web recommendations, ambient capture, proactive coaching, voice, vision, gesture, spatial/holographic UX, or other Jarvis roadmap features. Those remain gated until all Memory Search Agent work is complete and validated.

## Completion gate

Mark V1-13 complete only after full repository CI passes on the exact PR head containing this closeout and its regression tests.

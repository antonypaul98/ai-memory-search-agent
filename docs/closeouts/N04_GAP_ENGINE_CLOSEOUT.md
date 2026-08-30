# N-04 Gap Engine Closeout Candidate

Status: validation pending

## Canonical acceptance target

`FEATURE_IDEAS.md` defines N-04 as detecting when the user has a goal but insufficient saved knowledge for it (summarized there as “you wanted X but never saved Y”). `KNOWLEDGE_ENGINE.md` describes N-04 as detecting holes in memory relative to stated goals.

## Implemented behavior

The existing `GapAgent` provides the smallest deterministic implementation of that contract:

- analyzes only the authenticated tenant's reflection-goal registry data;
- includes explicitly requested goals even when they have zero saved memories;
- reports coverage gaps with evidence (`memory_count`, configured minimum);
- reports source-diversity gaps with evidence (`distinct_sources`, configured minimum);
- reports stale/never-reviewed knowledge with evidence;
- emits an actionable per-goal notification only when at least one gap exists;
- performs no network fetch, autonomous memory write, or mandatory LLM call.

Because the repository does not currently define a curriculum/ontology for inferring an arbitrary missing subtopic `Y`, N-04 does not fabricate one. It grounds gaps only in observable goal coverage, source diversity, and review state. Reverse Memory N-06 consumes those grounded gaps to recommend the next action.

## Acceptance evidence

`tests/test_gap_agent.py` already covers:

- an explicit requested goal with zero saved memories producing an actionable coverage/source-diversity gap;
- one actionable notification per gap-bearing goal;
- no gap for a sufficiently covered, recently reviewed goal;
- evidence-backed stale and single-source gaps;
- tenant isolation during goal discovery;
- authenticated API scoping.

## Safety / architecture checks

- deterministic output for the same registry state and request;
- tenant-scoped registry reads;
- evidence retained on every finding;
- no invented missing topic;
- no cross-tenant data access;
- no autonomous writes;
- no mandatory AI.

## Closeout gate

Do not mark N-04 complete until the full repository CI workflow passes on the PR containing this closeout record. If CI passes, reconcile the stale N-04 status in `KNOWLEDGE_ENGINE.md` and `FEATURE_IDEAS.md` during the source-of-truth documentation pass.

Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, and hardware work remain out of scope.

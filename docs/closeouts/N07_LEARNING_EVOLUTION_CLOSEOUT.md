# N-07 Learning Evolution — Acceptance Closeout Candidate

Status: **Validation pending**

## Canonical contract

`KNOWLEDGE_ENGINE.md` defines N-07 as memory improving over time from usage without full re-ingest. `FEATURE_IDEAS.md` summarizes the acceptance target as re-ranking/re-summarizing without full re-ingest.

## Implementation mapping

- `app/services/learning_evolution_service.py` converts tenant-local explicit helpful/not-helpful feedback and views into a small deterministic ranking adjustment.
- Explicit feedback is bounded, view influence is weaker, and total learning influence is capped so learned preference can break close ties without rescuing weak evidence.
- Search counts are deliberately excluded to prevent retrieval from reinforcing itself.
- `SearchService` applies the learning signal as an additive ranking layer while retaining the original relevance/similarity evidence score for auditability.
- Learning metadata failure is fail-open: core retrieval continues unchanged.
- The feature performs no network fetch, mandatory LLM call, autonomous content write, or full re-ingest.

## Acceptance evidence

Existing regression coverage in `tests/test_learning_evolution.py` proves bounded positive/negative learning, self-reinforcement protection, tenant-scoped usage lookups, unchanged evidence scores, tie-breaking from explicit feedback, and fail-open behavior.

`tests/test_learning_evolution_acceptance.py` adds the end-to-end acceptance regression: the same already-indexed results are searched before and after later helpful feedback. Their order evolves only after that tenant-local usage change, while the underlying evidence score remains unchanged and no repository/memory write occurs.

## Validation gate

Do not mark N-07 complete until the full repository CI workflow passes on the PR containing the dedicated acceptance regression.

No Jarvis-specific voice, vision, gesture, spatial, holographic, ambient-capture, or hardware work is part of this closeout.

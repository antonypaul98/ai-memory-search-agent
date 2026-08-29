# N-02 Verification Engine Closeout

**Status:** Acceptance-complete for the Memory Search Agent roadmap

## Scope

N-02 requires claim-level verification of chat answers against retrieved evidence while preserving deterministic behavior when optional AI is unavailable. This closeout does not add Jarvis-specific voice, vision, gesture, spatial, hologram, or ambient-agent behavior.

## Acceptance evidence

- Every answer sentence is segmented into a claim and receives a deterministic verification status: `supported`, `uncertain`, or `unsupported`.
- Supported/uncertain claims carry retrieved `evidence_id` references; unsupported claims are explicitly labeled rather than silently treated as grounded.
- Numeric claims are penalized when factual numbers are absent from the cited evidence, preventing lexical overlap from hiding unsupported figures.
- Chat responses expose `verification` with aggregate score, per-claim status, evidence IDs, and supported/uncertain/unsupported counts.
- Verification runs after synthesis for both deterministic and optional-provider answers, so optional AI does not bypass the evidence gate.
- Adversarial regression coverage includes fabricated uptime/location claims, mismatched numeric claims, mixed supported/unsupported sentences, and empty-answer behavior.

## Implementation anchors

- `app/services/verification_engine.py`
- `app/models/verification.py`
- `app/services/chat_service.py`
- `tests/test_verification_engine.py`
- `tests/test_chat_service.py`

## Safety and architecture invariants

- Verification is deterministic and does not require an LLM call.
- Verification uses only evidence already retrieved for the current user-scoped chat request.
- Evidence IDs are derived from supplied memory records and are not accepted from arbitrary external state.
- No credentials, private content, or provider secrets are added to logs or roadmap evidence.
- Optional AI remains on-demand; deterministic synthesis and verification remain available without it.

## Scope boundaries

Source freshness scoring remains part of trust/freshness work, while cross-source contradiction reconciliation belongs to the separate consensus engine. Those capabilities must not be conflated with N-02 claim-to-evidence verification.

N-02 is therefore acceptance-complete for its defined per-claim verification contract.

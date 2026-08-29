# F-12 Answer Generation & Synthesis Closeout

**Status:** Complete  
**Scope:** Grounded Memory Search answer generation across the deterministic default path and the optional on-demand LLM synthesis path.

## Acceptance criteria evidence

`MASTER_SPEC.md` already marks deterministic synthesis complete and leaves only the optional LLM path partial. With F-16 now validated and merged, the remaining F-12 acceptance gap is satisfied without adding a second synthesis implementation.

The repository now provides the required behavior:

- `app/services/answer_synthesizer.py` provides the deterministic default path and returns grounded output only when evidence is strong enough.
- Deterministic synthesis formats supported component/list, procedural, and summary answers from retrieved evidence and falls back when evidence is insufficient.
- The optional provider path is disabled by default through `llm_provider=none`; Memory Search therefore remains usable without external AI, credentials, or billing.
- `app/services/llm_provider.py` constrains structured LLM synthesis to supplied evidence IDs and rejects hallucinated or out-of-window citations.
- Missing provider configuration, missing credentials/model, malformed provider output, or invalid evidence references fail safely back to the deterministic path rather than fabricating a grounded answer.
- Provider credentials are environment-indirected and are not inserted into prompts or repository state.

## Regression coverage

Primary deterministic coverage: `tests/test_answer_synthesizer.py`, together with the existing answer-generator and chat-service/API tests referenced by the canonical spec.

Optional-provider coverage: `tests/test_llm_provider.py` verifies disabled-provider behavior, request contracts, credential indirection, malformed structured output, hallucinated evidence rejection, and prompted-evidence-window enforcement.

These tests preserve the core product contract that synthesis is grounded in retrieved user evidence and that optional AI cannot silently expand the evidence boundary.

## Privacy, provenance, and cost boundary

F-12 does not introduce ambient or continuously running AI. The deterministic path remains available and authoritative when optional AI is disabled or fails. Optional provider calls occur only on demand, and accepted structured answers may reference only evidence supplied for that request, preserving provenance and user-scoped evidence boundaries.

## Jarvis boundary

This closeout is limited to Memory Search answer generation. It adds no voice, vision, gesture, spatial/holographic interaction, ambient capture, or other Jarvis-specific behavior.

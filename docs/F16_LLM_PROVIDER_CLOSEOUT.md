# F-16 LLM Provider Closeout

**Status:** Complete  
**Scope:** Optional, on-demand LLM synthesis/capsule generation only. The deterministic Memory Search path remains the default and authoritative fallback.

## Acceptance criteria evidence

`MASTER_SPEC.md` requires the full pipeline to work when `llm_provider=none` and requires integration/contract coverage for optional LLM paths before F-16 can be marked complete.

The repository now satisfies that gate:

- `app/services/llm_provider.py` keeps `none` as the default and returns no provider when optional AI is disabled.
- Ollama is exercised through its `/api/chat` contract.
- OpenAI-compatible providers are exercised through `/v1/chat/completions`.
- API keys are resolved indirectly from the configured environment-variable name; credentials are not stored in repository state or prompts.
- Missing OpenAI-compatible credentials/model fail closed to the deterministic path without making an HTTP request.
- Structured synthesis accepts only evidence IDs supplied to the model; hallucinated or out-of-window evidence IDs are rejected.
- Malformed provider output returns `None`, preserving deterministic fallback behavior.
- Existing answer-generator/synthesizer tests continue to cover the no-LLM path.

## Regression coverage

Primary contract coverage: `tests/test_llm_provider.py`.

The contract suite specifically covers provider selection, Ollama request shape, OpenAI-compatible request shape, environment-indirected bearer credentials, missing configuration, malformed structured output, and evidence-ID grounding enforcement.

## Privacy and cost boundary

F-16 does not make AI continuously active. Provider calls occur only when an optional provider is configured and the calling Memory Search operation requests synthesis/capsule generation. CI uses mocked provider contracts and therefore requires no external credentials, billing account, or private model endpoint.

## Jarvis boundary

This closeout is a Memory Search capability only. It does not add voice, vision, gesture, spatial/holographic interaction, ambient recording, or any other Jarvis-specific feature.

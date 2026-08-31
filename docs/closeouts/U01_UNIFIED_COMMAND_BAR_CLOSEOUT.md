# U-01 Unified Command Bar — Acceptance Closeout

## Status

Acceptance-complete for the current Memory Search Agent scope.

## Accepted behavior

- The Chrome extension exposes one command input that routes through the agent command planner.
- The same input supports search, grounded ask/chat, and save/capture intents.
- Search and ask render their results in the command surface instead of requiring separate input widgets.
- Save/capture reuses the existing `SAVE_TO_MEMORY` flow, preserving canonical ingest, provenance, deterministic deduplication, and existing capture status handling.
- Bulk/import-style actions remain confirmation-gated and use single-use confirmation tokens before execution.

## Safety and architecture invariants

- No second write path is introduced for capture; the command bar delegates to the existing canonical save path.
- Bulk actions do not silently execute or auto-open before required confirmation.
- Tenant identity continues to be supplied by the authenticated backend rather than selected by the client.
- Search/capture command routing is deterministic and does not require an LLM.
- Optional answer synthesis remains on-demand and retains the existing deterministic fallback.

## Regression coverage

`tests/test_unified_command_acceptance.py` locks the current acceptance boundary by checking:

1. one command form/input feeds the planner;
2. search, ask, and save/capture all route from that same input;
3. save/capture reuses `SAVE_TO_MEMORY`;
4. bulk writes preserve the explicit confirmation-token gate;
5. bulk handoffs are not silently opened before confirmation.

## Boundary

This closeout does not add voice input, ambient capture, vision, gesture, spatial interfaces, holograms, autonomous side effects, or other Jarvis-specific behavior.

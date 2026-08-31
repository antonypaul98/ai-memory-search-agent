# N-08 Cross-source Dedup UI Acceptance

**Status:** Acceptance-complete for the currently specified Memory Search scope  
**Feature:** `N-08` in `FEATURE_IDEAS.md`  
**Acceptance summary:** Show duplicate memories; provide a user-reviewed merge action.

## Accepted behavior

The current PWA topic workspace already satisfies the repository-controlled N-08 acceptance boundary:

- duplicate candidates are loaded from the intelligence duplicate endpoint and presented for user review;
- each candidate preserves the explanatory context already returned by the service, including relationship, shared topics, diversity score, and evidence text;
- both memories remain individually inspectable before any merge;
- merge buttons explicitly state which memory is retained and which is merged;
- the client resolves each external YouTube identifier to its canonical memory record before requesting a merge;
- the merge action is guarded by an explicit user confirmation dialog;
- the merge request uses the existing confirmed lifecycle merge API and records `duplicate_merge` as the reason;
- no background or autonomous duplicate merge is introduced.

## Regression coverage

`tests/extension/duplicate_merge_ui.test.mjs` protects the critical safety contract by asserting that the UI requires `window.confirm(...)`, resolves canonical records, exposes both merge directions, and sends an explicitly confirmed merge request.

Repository-wide CI remains the release gate for this closeout.

## Architectural boundaries preserved

This acceptance does not change retrieval, canonicalization, provenance, evidence, tenant isolation, or trust computation. It also does not add mandatory AI calls. Duplicate discovery can continue to evolve independently, but destructive/consolidating actions remain human-confirmed.

This milestone is part of the Memory Search Agent roadmap only. It does not promote or begin Jarvis voice, vision, gesture, spatial, holographic, ambient-capture, or hardware work.

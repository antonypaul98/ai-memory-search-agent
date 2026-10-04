# Jarvis V1 Gate Ledger

Updated: 2026-10-03.

**Jarvis V1 Gate: 4/12 cleared — 8 remaining.**

Jarvis V1 starts only after the Memory Search transition reached 29/29 on main
(PR #386, merge `82338ad523b1c7d2601800b6b5b1db710dc642bc`). Jarvis credits do not
recount Memory Search acceptance.

## J01 — Core runtime

Status: **Verified on main through PR #387.**

Acceptance:
- one authenticated natural-language Jarvis entry point;
- reuse the accepted Memory Search command router/runtime rather than a parallel stack;
- safe read-only search/ask/help intents can execute end-to-end;
- authenticated tenant identity is propagated into execution;
- write/bulk/external intents cannot silently execute;
- response exposes the deterministic plan and bounded execution outcome.

Implementation:
- `app/services/jarvis_core_runtime.py`
- `app/models/jarvis.py`
- `app/api/routes/jarvis.py`
- `POST /api/v1/jarvis/run`

Regression:
- `tests/test_jarvis_core_runtime.py`

Evidence:
- Branch starts from Memory Search final merge `82338ad523b1c7d2601800b6b5b1db710dc642bc`.
- Exact-head `6c5506bb56e25518e36bdfffda97e7d1ca8bda45`: CI run
  `36209411798` succeeded.
- Merge `b87eb8d11a7e3e5d05b5be5aa7674c3f5125112f` is an ancestor of
  fetched main `ef1ed00f7916d81b690d4f930130dc30d04e3ff2`.

## J02 — Permissions and action safety

Status: **Verified on main through PR #390.**

Reuses tenant-bound, expiring, single-use confirmation for bulk handoff; other
writes remain gated. Regression coverage includes missing/tampered tokens,
cross-tenant rejection and replay rejection.

- Exact-head `5d03725577c6fdc17ca8e5caf7ad1d788181eee9`: CI run
  `36529911799` succeeded.
- Merge/current fetched main: `ef1ed00f7916d81b690d4f930130dc30d04e3ff2`.

## J03 — Context and personal memory

Integration: **PR #391 merged; acceptance recorded by this CI-gated receipt.**

- Exact repaired head: `36d0c4f2f72afb35dbe47ec78b16e5377ee0094a`.
- CI run `36669438702`: 1,376 Python tests passed, 1 skipped;
  30 extension tests and AHME benchmark passed.
- Merge: `324164bc685b8b2c11c0bc618fa38371952a5eb3`, fetched locally;
  includes Home merge `55c8ff214c0eb6fab38645528b943133629b8a79`.
- Combined Jarvis/Home targeted regressions: 54 passed on that merged main.
- This receipt requires fresh exact-head CI before integration and final main CI
  verification. Branch-local or pending CI is not an acceptance credit.

Reuses the authenticated tenant's existing Memory Search results and actual chat
`sources`, preserving timestamp citations and bounded result count. Failed commands
and non-memory actions do not project context. No parallel memory store is added.
Local targeted suite: 14 passed. The repaired head passed its own exact-head CI; no earlier-head result substitutes for it.

Remaining J05–J12:
J05 vision/Home;
J06 screen/device awareness; J07 computer-use actions; J08 proactive triggers;
J09 multi-device continuity; J10 gestures; J11 spatial interface; J12 integrated
stability/security/release.

## J04 — Bounded voice transcript ingress

Status: implementation locally validated; PR #394 pending exact-head CI and merged-main verification. No new gate credited until acceptance.

`POST /api/v1/jarvis/voice` accepts a nonblank transcript of at most 2,000
characters and converts it to the existing Jarvis request. Authenticated tenant,
context, result limit and confirmation token pass through the same runtime.
Write gating, bulk single-use confirmation and J03 provenance remain unchanged.
This is transcript ingress only: no microphone capture or speech recognition
is claimed. J05 is not started. Home remains read-only; physical Mac camera
acceptance is pending.

Local Python 3.11.16 at `a228a875976f4c0d939933b9bd102527bd944345`: 49 passed,
zero skipped across Jarvis core, command router and unified command acceptance.
The acceptance receipt revision must pass its own exact-head CI before merge.

J04 completion: PR #394 merged as `f7713adfcbe961660b2759cbfcfc2eda103aad17` after exact-head CI
`37155231659` at `2d212bf7de1ae71aaa53b0bba3fc29c58f4907a6`. Merged-main CI `37155654485`
succeeded; 49 targeted tests passed on merged main. J04 is accepted as bounded
transcript ingress. J05 not started; physical camera acceptance remains pending.

## J05 — Vision/Home software ingress

IN PROGRESS. Authenticated physical-memory query slice is defined in
`docs/J05_HOME_QUERY_ACCEPTANCE.md`. No fifth gate credit until complete acceptance;
physical Mac-camera evidence remains pending.

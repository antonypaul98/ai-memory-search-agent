# Home Mac acceptance software checkpoint

Starting main: `ef1ed00f7916d81b690d4f930130dc30d04e3ff2`.
Canonical branch: `home-vision/mac-hardware-acceptance-v3`.

PR #389 multi-frame evidence is already integrated and is not reimplemented.
The original hardware branch contains no unique work. v2's hardware code is
identical to v3's code; v3 adds the missing configuration regressions and includes
current main. Both older branches are superseded for development and retained.

This checkpoint validates configuration before camera access, preserves bounded
acquisition and confirmations, explicitly closes retained iterators on early return
or exceptions, and releases OpenCV handles when the open-status probe fails.
Existing tenant/session identity propagation and provenance are unchanged.

Local validation: 40 focused capture/configuration/lifecycle regressions passed;
193 Home tests passed, 5 skipped. The optional torch adapter tests were excluded
because torch is unavailable locally. Full CI and trained-vision/PostgreSQL smoke
must pass on the exact head before merge. Tests use injected/mock devices, never
a physical webcam in CI.

**Physical Mac webcam acceptance: PENDING.** No physical camera was accessed.
Next hardware action: on a consenting Mac, configure the authenticated capture
stack and invoke `app.services.home_agent.hardware_smoke.run_hardware_smoke`
with a real OpenCV device and `require_event=True`; retain bounded frame,
physical-memory event and cleanup evidence. The dedicated hardware-acceptance
CLI is on the unmerged `home-vision/mac-hardware-cli` branch, not yet on `main`.
CI mocks cannot satisfy physical-camera acceptance.

## Verified software integration

- PR #392 merged as `55c8ff214c0eb6fab38645528b943133629b8a79`.
- Exact head `bb167c8856e292331c535c144c18c65574d54dd9` passed CI
  `36669705131`: 1,384 Python tests passed, 1 skipped; 30 extension tests
  and AHME benchmark passed.
- Exact-head trained-vision/PostgreSQL smoke `36669705081` succeeded.
- Main was fetched and its 40 focused capture regressions passed.
- Later combined main `324164bc685b8b2c11c0bc618fa38371952a5eb3` includes
  J03 and Home; all 54 combined targeted regressions passed.
- Final integrated CI remains mandatory for this receipt and its merged main.
  The superseded Home-only main CI was cancelled by the later J03 merge, not
  counted as successful. Physical Mac acceptance stays pending.

## Pending hardware-acceptance CLI release

- Entry point: `python -m app.services.home_agent.hardware_acceptance_cli`.
- On a consenting Mac only, provide a trusted local `--capture-factory module:callable`, authenticated `--session-id`, `--user-id`, `--source-id`, `--location`, plus both `--allow-physical-camera` and `--require-event`.
- Validation rejects nonfinite or unrepresentable intervals, invalid confidence, unbounded or inconsistent frame/confirmation settings, and missing consent before loading the camera factory.
- Require exact final PR-head core CI and Home Vision Smoke, then merged-main CI, before software handoff to Jarvis. Successful push CI alone does not complete the PR acceptance gate.
- Physical acceptance remains **PENDING** until an observed real camera memory event and cleanup receipt on a consenting Mac. Never commit private frames, tokens or personal session identifiers.

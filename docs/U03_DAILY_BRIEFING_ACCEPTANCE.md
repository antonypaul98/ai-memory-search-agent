# U-03 / G27 Daily Briefing acceptance

Status: **Accepted in repository-controlled Memory Search scope**

## Contract

The daily briefing must be a grounded, opt-in review/gap digest with explicit notification preferences. It must preserve tenant isolation and evidence references, remain deterministic without mandatory AI, and stay bounded.

## Implementation evidence

Implemented by PR #370 (`20f4f49302f141ec2cb8a6df468055e2b5b24d26`) in `app/services/daily_briefing_service.py`.

The service:

- composes review, gap, and goal signals without invoking AI or mutating memory;
- rejects any signal whose tenant does not match the requested tenant;
- retains upstream `evidence_ids` on every included signal;
- sorts deterministically by priority and signal ID and bounds each section;
- defaults notifications to disabled;
- permits notification only when both `daily_briefing` and global `notifications_enabled` preferences are explicitly true;
- requires timezone-aware generation timestamps.

## Regression evidence

`tests/test_daily_briefing_service.py` covers:

1. deterministic review/gap/goal composition and evidence retention;
2. cross-tenant rejection;
3. default-off notification behavior and the two explicit opt-in preferences;
4. bounded sections with stable tie-breaking;
5. rejection of naive timestamps.

Exact PR #370 head `20f4f49302f141ec2cb8a6df468055e2b5b24d26` passed CI run #1326 (`35891508819`). The implementation was merged to `main` as `1b0a50fb...` and remains present in the current green ancestry.

## Boundary

This acceptance covers the repository-controlled Memory Search U-03 contract. It does not claim OS/provider notification delivery, autonomous scheduling outside explicit user configuration, or Jarvis voice/vision/gesture/spatial behavior.

No acceptance criterion is weakened by this reconciliation; it records evidence for already-merged implementation and tests.
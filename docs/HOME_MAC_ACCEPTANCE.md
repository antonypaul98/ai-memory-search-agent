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
After software integration, execute the documented hardware smoke on a consenting
Mac with a real camera and retain its bounded frames/event/cleanup evidence.

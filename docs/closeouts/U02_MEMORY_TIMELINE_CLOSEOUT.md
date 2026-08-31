# U-02 Memory Timeline — Acceptance Closeout

## Status

Acceptance-complete for the current Memory Search Agent scope.

## Accepted behavior

- The PWA exposes a dedicated Memory Timeline route.
- Memories can be browsed chronologically using recently-saved and first-learned modes.
- Timeline entries can be grouped by day, week, month, or shown as a flat list.
- Topic filtering is tenant-scoped through the authenticated intelligence timeline API.
- Save-time goals are deterministically promoted to `PROJECT` topics during intelligence indexing, so the same topic filter supports browsing memories by saved goal without a second goal index or an AI call.
- Timeline rendering remains bounded and escapes user-controlled strings.

## Safety and architecture invariants

- The authenticated user ID is supplied by the server-side auth dependency; clients cannot select another tenant.
- No mandatory LLM/remote AI call is introduced for timeline browsing or goal filtering.
- Existing canonical memories and provenance are read, not rewritten, by this view.
- No merge, delete, external side effect, or irreversible action is performed by timeline browsing.

## Regression coverage

`tests/test_timeline_acceptance.py` locks the current acceptance boundary by checking:

1. date grouping and chronological modes remain wired in the PWA;
2. the topic/goal filter remains wired to the timeline API;
3. the API forwards the authenticated tenant plus requested topic and limit;
4. saved reflection goals remain indexed as project topics.

## Boundary

This closeout does not add Jarvis-specific proactive behavior, voice capture, vision, gesture, spatial UI, holograms, or ambient monitoring. It also does not claim that future calendar-style visualizations or cross-device native timeline experiences are complete.
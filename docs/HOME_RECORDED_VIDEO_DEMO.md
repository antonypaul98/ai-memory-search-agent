# One-camera offline recorded-video replay (experimental)

This demo harness reuses local OWL-ViT, tentative frame association, the
detector-confirmed visible inventory, private JSONL event journal and
last-confirmed JPEG evidence. It does not access a physical camera, upload
footage, call a paid API or prove physical object identity.

Use a consented, locally stored, genuinely recorded video of one room with a
distinguishable object moving, disappearing and reappearing. From the repository
root with the optional Home vision dependencies installed:

    python -m scripts.home_recorded_replay \
      --video /path/to/consented-room-video.mp4 \
      --model-path "$HOME/.local/home-agent-test/models/owlvit-base-patch32" \
      --output-dir "$HOME/PrivateHomeAgent/replay-001" \
      --room-name office --sample-every 3 --max-scans 90

The model must already exist locally. The output directory must not exist
and is created privately (0700). The journal is events.jsonl (0600);
up to 256 JPEG event crops are saved under events-evidence/ (0600).
No network requests are made by the replay code. A failed inference, EOF,
or an undecodable frame never becomes a missing-object event. A successful
empty detection may mark an object NOT_VISIBLE or POSSIBLE_EXIT, not out
of the room. A re-entry is tentative, not independently verified identity.

The summary reports detector-event statuses only. The field
complete_transition_sequence_observed requires an ordered VISIBLE ->
MOVED_IN_FRAME -> NOT_VISIBLE/POSSIBLE_EXIT -> REAPPEARED_TENTATIVE pattern
for one session-local tentative track with a consistent label. It does not
prove a witnessed frame crossing, persistent physical identity, or that the
object left the room. Missed detections can produce a similar event pattern.
Last-visible positions are coarse camera-frame coordinates, not furniture-level
placement. Scan timestamps are replay indexes, not video or wall-clock timestamps.

Synthetic red-rectangle videos in CI test decoding and event wiring only.
For real recorded-footage acceptance, annotate actual source frames showing
initial visibility, movement, a witnessed boundary crossing, absence and
re-entry of a distinguishable object. Compare every sampled detector box,
visible inventory, status and saved crop with those annotations; record false
disappearances from detector misses and ambiguity from occlusion or duplicate
objects. A complete status pattern alone is not an acceptance pass.
A separate consenting physical Mac camera test is still required.

Explicit stopped-session journal/crop unlinking is available through
app.services.home_agent.frame_session_erasure (see
docs/HOME_SINGLE_CAMERA_FRAME_EVIDENCE.md), but automatic retention expiry,
backup/copy deletion and full concurrent-writer safety remain unverified.
Do not claim privacy-complete erasure. Avoid videos with other people without
consent: object crops can incidentally contain people.


## Ground-truth audit (offline, reviewer supplied)

For the demo gate, independently inspect the actual fixed-camera video frame by
frame. Record every sampled scan with a bounding box for the *visible part* of
one distinguishable object, and one of VISIBLE, CROSSING_OUT, OUT_OF_FRAME,
CROSSING_IN. Do not infer a crossing from a missing detector box. A fixed camera,
manual review, and the video's SHA-256 digest must be explicitly recorded.

Annotation JSON schema (example shape; fill all sampled scans, not just these):

    {
      "schema_version": 1,
      "video_sha256": "<64 lowercase hex characters>",
      "camera_fixed": true,
      "manual_frame_review_completed": true,
      "object_label": "cup",
      "sample_every": 1,
      "samples": [
        {"scan": 1, "frame_index": 0, "state": "VISIBLE", "box_xyxy": [10, 10, 50, 50]},
        {"scan": 2, "frame_index": 1, "state": "CROSSING_OUT", "box_xyxy": [25, 10, 65, 50]},
        {"scan": 3, "frame_index": 2, "state": "OUT_OF_FRAME", "box_xyxy": null},
        {"scan": 4, "frame_index": 3, "state": "CROSSING_IN", "box_xyxy": [25, 10, 65, 50]},
        {"scan": 5, "frame_index": 4, "state": "VISIBLE", "box_xyxy": [10, 10, 50, 50]}
      ]
    }

The source hash must be computed from the exact original video, and the scan
interval must equal the replay's --sample-every. The replay now stores the
source video's SHA-256 digest, sampled frame index and sampling interval in
every journal row; the audit rejects missing or inconsistent journal origins.
The replay also rejects a video whose bytes change between its initial and
final hash checks. This guards accidental source mixing, not deliberate
forgery, tampering between checks, or proof of who reviewed the video. For sample scan N (starting
at 1), frame_index is (N-1) * sample_every (zero-based). The example above is
illustrative metadata, not a reviewed real video or acceptance evidence.

Run after replay (with its private journal still present):

    python -m scripts.home_recorded_ground_truth \
      --video /path/to/consented-room-video.mp4 \
      --annotations /path/to/reviewed-annotations.json \
      --journal "$HOME/PrivateHomeAgent/replay-001/events.jsonl"

The audit compares annotated visibility with journal detections, checks
box overlap, detects false absences and unexpected detections, and checks
referenced private JPEG crops by decoding bounded image pixels. The separate
pixel diagnostic below compares those crops against the decoded source frames;
this ground-truth command alone does not establish pixel correspondence or
physical identity. It rejects
mismatched annotation/video or journal/video hashes, inconsistent source frame
sampling, incomplete scan annotations, unreviewed or non-fixed camera claims,
and unsafe evidence paths. Older unbound journals must be replayed from the
original source video; do not retrofit a hash into historical evidence. A reviewer-supplied annotation is
not independently authenticated, and the audit never automatically marks
the demo, physical identity or physical camera as accepted. Inspect actual
crops and ambiguous identities separately before any approval.


## Optional source-frame-to-JPEG pixel diagnostic

After the ground-truth audit, run the separate read-only crop correspondence
check on the same video and private replay journal:

    python -m scripts.home_recorded_pixel_audit \
      --video /path/to/consented-room-video.mp4 \
      --journal "$HOME/PrivateHomeAgent/replay-001/events.jsonl"

The diagnostic decodes the recorded source frames and reconstructs the
detector-box crop, including the immediately preceding confirmed crop for a
NOT_VISIBLE/POSSIBLE_EXIT event. It compares decoded private JPEG pixels using
a bounded mean absolute RGB error (default 22/255 per channel) to tolerate
JPEG compression. It reports matched, mismatched and unverifiable scan
numbers. A missing or duplicate reference, source hash mismatch, invalid
sampling, unsafe image path, malformed source box or non-private crop fails
closed. No pixels are exported, and no model or camera is opened.

This is a *diagnostic*, not a cryptographic signature or proof that a
reviewer's annotation is correct. Similar-looking but different crops may
pass a tolerant pixel comparison. A positive pixel_correspondence_complete
requires at least one evidence reference and zero mismatches/unverifiable
references, but automatic_demo_acceptance, physical_identity_verified and
physical_camera_tested remain false. Human inspection of the real source
frames and crops, the privacy/retention gates, independent review and
separate physical camera acceptance remain required.

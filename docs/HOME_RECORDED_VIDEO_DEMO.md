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

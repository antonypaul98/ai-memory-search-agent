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

The summary reports only observed statuses. The field
complete_transition_sequence_observed means the journal contains VISIBLE,
MOVED_IN_FRAME, a disappearance status and REAPPEARED_TENTATIVE. It does not
prove a specific physical object exited and returned. Last-visible positions
are coarse camera-frame coordinates, not furniture-level placement.
Scan timestamps are replay indexes, not video or wall-clock timestamps.

Synthetic red-rectangle videos in CI test decoding and event wiring only.
For real recorded-footage acceptance, review actual source frames and saved
event crops against visible motion and check failures, occlusion, duplicate
objects and consent. A separate consenting physical Mac camera test is
still required. Automatic retention/erasure is not yet verified; erase
local output when no longer needed. Avoid videos with other people without
consent: object crops can incidentally contain people.

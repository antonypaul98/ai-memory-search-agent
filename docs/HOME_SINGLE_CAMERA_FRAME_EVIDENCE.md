# One-camera private event image evidence (experimental)

The local preview can keep a detector-confirmed **frame-relative** inventory
and an opt-in private JSONL journal. To additionally save small event crops:

```sh
python -m app.services.home_agent.live_preview --allow-camera \
  --max-seconds 120 \
  --event-log-file "$HOME/PrivateHomeAgent/events.jsonl" \
  --room-name "office" --save-event-crops
```

Create a new private destination for each run; the parent directory must be
private (0700). Existing logs or evidence directories are never overwritten.
The journal stores a relative `evidence_image` filename for each event whose
crop was actually saved, or `null` when no image exists. The crop directory is
`events-evidence/` beside the journal. JPEGs are 0600, at most 320x320 pixels,
and limited to 256 images per session. Images of detections labeled `person`
are excluded from automatic crop saving. This is **not** a guarantee that other
people cannot appear incidentally in an object crop. No images are uploaded.

The crop on `NOT_VISIBLE` or `POSSIBLE_EXIT` comes from the **last successful
detector scan in which the object was visible**, not the later frame in which it
was missing. The event does **not** prove that the object crossed the camera
boundary or left the room. `REAPPEARED_TENTATIVE` is a tentative track
association, never independently verified physical identity. Object positions
are coarse camera-frame coordinates, not invented furniture descriptions.

Without `--save-event-crops`, no automatic images are saved. The existing
manual S snapshot and optional MP4 recording are separate explicit actions.
Deletion and retention of these local files remain the user's responsibility;
this experimental feature does not claim a verified privacy-erasure workflow.

Validation requires synthetic event/permission tests, exact-head Core CI and
Home vision smoke, then separate consenting physical Mac camera acceptance.

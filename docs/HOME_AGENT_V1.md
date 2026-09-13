# Home Agent V1 implementation and acceptance

Updated: 2026-09-13. **V1 incomplete.** This is a modular extension of the existing
Postgres physical-memory store and authenticated query routes, not a second database.

## Implemented vertical slice

`HomeImageIngestService` decodes a bounded local PNG/JPEG, requires active tenant/source
consent both before detection and before persistence, and explicit location/time, invokes an `ImageDetector`, strips EXIF/GPS, and
stores evidence and observations atomically through `PostgresHomeImageStore`.

`LocalOwlViTDetector` performs CPU inference with an already-downloaded OWL-ViT
checkpoint. No private image is uploaded and no model is downloaded during ingestion.
The adapter follows the [official OWL-ViT interface](https://huggingface.co/docs/transformers/en/model_doc/owlvit).
Its output scores are uncalibrated detector scores, not a probability that an object
is still at that location or that it is a particular person's possession.

Canonical class IDs are deterministic and tenant-scoped. They group observations
of a class such as `keys`; they do **not** assert physical instance identity.
Multiple objects in one frame have distinct observation IDs and share one evidence
frame. The existing sightings table and last-seen query service remain the retrieval
foundation. `describe_observation` supplies class ID, observation ID, bounding box,
frame hash, and detector provenance. Source and room metadata are supplied explicitly.

The first committed ingestion for a tenant/frame/source/location/time tuple is
immutable. Retries do not replace its scores or add detections from a different
model. Failed transactions retain neither partial observations nor evidence.
Evidence is stored as private database bytes, never a public URL. `get_image` and
`delete_image` require exact tenant ownership. Deleting a frame removes linked
sightings and orphan class records. Automatic retention scheduling remains future work.

## Repeatable local demo

Install base plus optional detector dependencies:

```bash
python -m pip install -r requirements-home-vision.txt
```

Download the `google/owlvit-base-patch32` checkpoint separately using the Hugging Face
Hub client into a local directory. The smoke test pins model revision
`cbc355fb364588351c5d51c7f74465e8e7ec6f72`; use that revision for reproducibility. The runtime requires local model files and never
falls back to network inference. Configure the existing environment-owned Postgres
DSN (`POSTGRES_DSN_ENV`, default `DATABASE_URL`) for a development database.

Use your own JPEG/PNG and its real observation time; location is explicit metadata:

```bash
python -m app.services.home_agent.image_demo \
  --image /absolute/path/kitchen.png \
  --model-path /absolute/path/owlvit-base-patch32 \
  --tenant local-default --source phone --location 'kitchen counter' \
  --observed-at '2026-09-13T19:42:00+00:00' \
  --labels keys wallet --query keys --consent
```

The CLI prints actual persisted last-seen data, canonical/evidence references,
uncalibrated detection confidence, source and timings. It does not manufacture an
answer if detection/retrieval finds nothing. This is a local operator CLI; HTTP
callers must derive tenant identity from authentication, never a submitted tenant.
Existing authenticated `/home-agent/where-is` and `/history` can query these sightings.
The upload/evidence HTTP endpoints are not yet implemented.

## Validation and remaining acceptance

- Offline tests decode real PNG bytes with an explicitly fake detector. They cover
  normalization, metadata, evidence hashes, timestamps, malformed input and consent.
- Real-Postgres integration tests exercise persisted last-seen after restart,
  multi-object frames, two locations, another tenant, deduplication, evidence
  deletion, conflicting observations, rollback and safe retry.
- These fixtures do **not** certify trained-detector accuracy. A real checkpoint
  and representative household photographs must be exercised before V1 sign-off.
- Same-time conflicting observations remain visible in history and in structured
  `conflicting_locations`; answers explicitly preserve uncertainty. A full bounded
  same-time history page reports `history_truncated` instead of implying uniqueness.
- Aliases, user-confirmed instance identities, canonical location records/hierarchy,
  video extraction, automatic retention and camera/RTSP adapters remain open.
- The text/API layer currently accepts an object class, not free-form natural language.
- End-to-end trained-detector demo and final CI evidence must be recorded before
  checking the complete V1 definition of done. No completion percentage is asserted
  from implementation presence alone.

## Trained detector acceptance

Local inference on the pinned public COCO sample detected two cats and a remote
control, with scores approximately 0.287, 0.254 and 0.328. Detection took 486 ms
after model loading in this environment; this is one sample, not a latency SLA
or household/keys accuracy certification. The detector ID hashes checkpoint assets,
labels and threshold.

`python scripts/home_vision_smoke.py` is the repeatable full trained-detector +
Postgres smoke command. It requires a disposable `MEMORY_AGENT_TEST_POSTGRES_DSN`,
downloads a pinned public sample and model, stores two explicitly labeled demo
locations, restarts storage, verifies last-seen/evidence/tenant isolation, and
deletes only its randomly scoped fixture records. `Home vision smoke` CI runs
this separately for relevant Home Agent PRs; ordinary tests need no model download.

## V1 checklist accounting

This is a conservative 15-item implementation checklist, not a claim of household
accuracy or a replacement for the Memory Agent gate. PR #250 passed full CI and the
trained Postgres smoke; 12/15 items are met (80%), with three partial:

| Requirement | Status / evidence |
| --- | --- |
| Real image ingestion | JPEG/PNG decode and validation tests |
| Actual detection | Local pinned OWL-ViT and trained smoke |
| Canonical object storage | Partial: deterministic class IDs exist; aliases and confirmed instance identity remain |
| Persistent observations | Real Postgres integration and restart test |
| Timestamps | Timezone-aware, future rejection and ordering tests |
| Room/location | Partial: explicit room strings work; canonical location records/mapping remain |
| Evidence reference | Private frame, hash, observation linkage and ownership tests |
| Confidence | Original detector score retained; not treated as calibrated certainty |
| Where-is query | Partial: authenticated object-class API works; natural-language query normalization remains |
| Last-seen retrieval | Real Postgres latest/history and conflict tests |
| Tenant isolation | Cross-tenant read, evidence and deletion tests |
| Integration test | Real image parsing, stored observations and query |
| Reproducible demo | Pinned trained-detector Postgres smoke and local operator CLI |
| Documentation | This file and CURRENT_BUILD_STATE.md |
| CI green | Verify both CI and Home vision smoke on the exact PR head |

Remaining beyond these partial items: authenticated image upload/evidence delivery,
automatic retention policy, representative household/keys evaluation and the final
V1 acceptance review. Voice/video/CCTV do not block the local still-image V1.

Verified trained-smoke evidence: [run 34786095550](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/34786095550)
on PR #250 head `920941f339dd2f647ac14a35b407351aee324e53` passed with linked
evidence, detected `cat`, latest `demo living room`, original model score 0.286885,
653 ms detection / 720 ms ingestion. Full CI on that head: 1,046 passed.

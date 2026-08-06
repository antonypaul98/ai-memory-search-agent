# V1-2 YouTube Memory Agent

**Status:** Implemented  
**Last updated:** 2026-07-28  
**Role:** YouTube is the **reference connector** for all future sources.

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Clients: Extension Agent Popup · PWA · API                  │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  Capture / Videos / YouTube / Search / Chat routes           │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  IngestService (generic orchestrator)                        │
│    uses SourceConnector — never embeds yt-dlp/transcript API │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  ConnectorRegistry                                           │
│    youtube.v1 → YouTubeConnector                             │
│    (future: github.v1, pdf.v1, web.v1, …)                    │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  YouTubeConnector                                            │
│    fetch_metadata · detect_transcript · fetch_transcript     │
│    normalize → YouTubeMemory / NormalizedItem                │
└─────────────────────────────────────────────────────────────┘
```

**Rule:** YouTube-specific APIs (yt-dlp, youtube-transcript-api) live **only** inside `YouTubeConnector` (+ thin legacy facades that delegate to it).

---

## 2. Processing pipeline

```
Queued → Metadata → Transcript → Chunking → Embedding → Indexed → Completed
                                                              ↘ Failed → Retry → …
```

| Stage | Meaning |
|-------|---------|
| `queued` | Accepted into Memory |
| `metadata` | Fetching title/channel/… |
| `transcript` | Detecting & retrieving captions |
| `chunking` | Splitting timed text |
| `embedding` | Vectorizing chunks |
| `indexed` | Written to Chroma/SQLite |
| `completed` | Pipeline finished successfully |
| `failed` | Terminal failure (may enqueue retry) |
| `retry` | Scheduled for another attempt |

Capture status API exposes these stages for the extension poller.

---

## 3. Failure handling

| Failure | Behavior |
|---------|----------|
| Invalid URL | Fail immediately (no retry) |
| Metadata fetch error | Retry with exponential backoff |
| Transcript disabled / unavailable | Complete as **partial** (metadata indexed status recorded; no chunks) OR fail with `transcript_status=unavailable` — V1-2 records status and fails ingest for searchability (transcript required for chunks) with retry for transient fetch errors only |
| Transient YouTubeRequestFailed | Retry queue |
| Max attempts exceeded | Dead-letter (`dead_lettered=1`) |

**Idempotent saves:** same `(user_id, video_id)` skips when already indexed unless `force_refresh`.

---

## 4. APIs (additive)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/youtube/memories/{video_id}` | Full YouTube memory model |
| GET | `/api/v1/youtube/memories/{video_id}/related` | Related memories + strength |
| GET | `/api/v1/youtube/diagnostics` | Metrics & health for connector |
| POST | `/api/v1/youtube/retry-queue/process` | Process due retries |
| GET | `/api/v1/search` | Extended with filters (backward compatible) |

Existing `/videos/ingest`, `/capture/*`, `/chat` remain unchanged in contract.

---

## 5. Database (schema v6)

- `youtube_memories` — validated rich YouTube memory rows  
- `pipeline_runs` — stage history per capture/ingest  
- `connector_retry_queue` — backoff + dead-letter  
- `connector_metrics` — counters for observability  

---

## 6. Search & explanation

Hybrid AHME search plus optional filters: `channel`, `date_from`/`date_to`, `transcript_available`, `duration_min`/`duration_max`, `language`, `min_confidence`.

Each hit includes: `why_matched`, matching chunk text, confidence, related hints, duplicate flag, processing completeness.

---

## 7. Knowledge answers

Cross-video questions use existing grounded chat (`/api/v1/chat`) over indexed YouTube memories only. Synthesis must cite sources; fabrication of unsaved content is rejected by grounding checks.

Example intents supported via chat/search: summarize topic, find tutorial, compare creators, recommend next watch (from related + retrieval).

---

## 8. Extension points

Implement `SourceConnector` for GitHub/PDF/Web without changing `IngestService` core — register in `ConnectorRegistry`.

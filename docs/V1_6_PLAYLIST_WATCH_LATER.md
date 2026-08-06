# V1-6 — Playlist / Watch Later Polish

**Status:** Implemented (post-audit remediation 2026-07-29)  
**Last updated:** 2026-07-29  

Public playlist import is demo-ready in the PWA. Watch Later is **not scraped** and has no production OAuth in V1 — demos use a public playlist URL.

---

## 1. Goals (this phase)

1. **PWA playlist UX** — preview → confirm → ingest; real title/count/samples; progress UI; reflection + force refresh; pause / resume / retry-failed / cancel  
2. **API reliability** — clear errors for missing/invalid API key, private, empty, Watch Later/`list=WL`; size cap; mocked tests  
3. **Extension import chrome** — bookmarks preview → confirm → import; PDF upload via V1-4 APIs; deep-link to Workspace `#capture` for playlists  
4. **Watch Later honesty** — documented + UI “Coming soon / use public playlist URL”; no actionable Watch Later control  
5. **Light V1-9 prep** — demo Act 4 aligned; no store submission  

**Out of scope:** V1-7 command polish, Ontology, Enterprise Auth, RBAC, MCP, multi-tenancy, Consensus/Gap/Agents, Watch Later scraping, production Google OAuth.

---

## 2. Architecture (reused)

```
Public playlist URL
        │
        ▼
 POST /api/v1/playlists/preview  → PlaylistResolver
        │  title · video_count · sample_titles
        ▼
 User confirms in PWA Capture
        │
        ▼
 POST /api/v1/playlists/ingest
        │  reflection · force_refresh · playlist_max_videos
        ▼
 JobStore.create_playlist_job → JobWorker
        │
        ▼
 GET/POST /api/v1/jobs/{id}  (detail · pause · resume · retry-failed · cancel)
 DELETE /api/v1/jobs/{id}    (hard delete / cleanup)
```

Extension bookmarks/PDF call existing ImportManager / ConnectorIngestService routes — no new backend connectors.

---

## 3. APIs

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/v1/playlists/preview` | Returns real `title`, `video_count`, `sample_titles` |
| POST | `/api/v1/playlists/ingest` | Creates job; accepts `reflection`, `force_refresh`; enforces `PLAYLIST_MAX_VIDEOS` (default 500) |
| GET | `/api/v1/jobs/{id}` | Progress + items |
| POST | `/api/v1/jobs/{id}/pause` | Pause (no new claims) |
| POST | `/api/v1/jobs/{id}/resume` | Resume (blocked for cancelled/completed) |
| POST | `/api/v1/jobs/{id}/retry-failed` | Retry failed items (blocked for cancelled) |
| POST | `/api/v1/jobs/{id}/cancel` | Soft-cancel: status=`cancelled`, queued items cancelled; in-flight finish without resurrecting |
| DELETE | `/api/v1/jobs/{id}` | Hard delete job rows |
| POST | `/api/v1/capture/bookmarks/preview` | Extension + PWA |
| POST | `/api/v1/capture/bookmarks/import` | Extension + PWA |
| POST | `/api/v1/capture/pdf` | Extension + PWA |

**Error messaging (400):** missing/invalid `YOUTUBE_API_KEY`, private/not found, empty playlist, Watch Later / Liked (`list=WL` / `list=LL`), oversize playlist. Watch Later is never fetched via scrape.

---

## 4. Watch Later policy

| Approach | V1-6 |
|----------|------|
| Scrape YouTube Watch Later | **Forbidden** |
| Production Google OAuth (`youtube.readonly`) | **Deferred** (post-V1 / verification) |
| Demo fallback | Paste a **public playlist URL** in PWA Capture |
| UI copy | Extension + PWA: “Coming soon — use public playlist URL” |
| Parser guard | `list=WL` / `list=LL` rejected before any network call |

Optional lightweight OAuth stub was **not** shipped; documented fallback is the default.

---

## 5. UX surfaces

### PWA Capture (`#capture`)

- Playlist URL → **Preview playlist** → confirm card (title, count, samples) → **Confirm import**  
- Playlist reflection + force refresh  
- Progress card (bar with `role="progressbar"`, counts, item statuses) — not raw JSON  
- Pause / Resume / Retry failed / **Cancel job**  
- Preview **Cancel** dismisses confirmation without starting a job  

### Extension popup (v1.2.0)

- **Import bookmarks** — optional `bookmarks` permission → preview → confirm (confirm disabled until preview succeeds)  
- **Upload PDF** — multipart to `/capture/pdf`  
- **Playlist in Workspace** — opens `{pwa_url}/#capture` (deep-link only; does not start ingest)  
- Watch Later callout + permissions row **Coming soon** (no import action)  

---

## 6. Tests

- `tests/test_playlists_v1_6.py` — mocked preview/ingest; private/empty/missing-key; WL/LL rejection; cancel/retry guards; max videos; atomic claim; deep-link helper  
- Existing `tests/test_distribution.py` — JobStore, parser, isolation, WL reject  

---

## 7. Demo (Act 4)

See `docs/V1_DEMO_SCRIPT.md` Act 4 — public playlist preview → confirm → job progress. Do not claim Watch Later import.

---

## 8. Known limitations

- Watch Later / private playlists require future OAuth  
- Large playlists depend on API key + job worker (`JOBS_ENABLED=true`) and `PLAYLIST_MAX_VIDEOS`  
- Extension playlist UI is a Workspace deep-link (popup too small for full job console)  
- yt-dlp fallback may be slower / flakier without `YOUTUBE_API_KEY`  
- Preview results are cached ~90s in-process so confirm ingest usually skips a second YouTube fetch  

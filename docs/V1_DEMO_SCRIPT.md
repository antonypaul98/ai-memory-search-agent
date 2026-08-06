# V1 Demo Script

**Purpose:** Repeatable 8–10 minute demo for Chrome Web Store video, LinkedIn, and investor/user reviews.  
**Prerequisites:** Backend running; extension loaded unpacked; sample data optional.  
**V1-9 status:** Script + `scripts/seed_demo.py` ready. **Video file is a human recording step** (not checked into the repo).

---

## Environment Setup (Pre-Recording)

```bash
source .venv_clean/bin/activate
JOBS_ENABLED=true AUTH_ENABLED=false PWA_ENABLED=true \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

1. Chrome → `chrome://extensions` → Load unpacked → select `extension/`
2. Extension popup → API base: `http://localhost:8000/api/v1` → confirm health shows connected (after V1-1)
3. Optional: clear `./data/` for clean demo, or run `python scripts/seed_demo.py` for registry titles/trust demos  
4. For Acts 5–6 (search/ask): save **1–2 real public YouTube videos** so embeddings exist (seed script does not fake vectors)

**Fallback if extension feature missing:** Use PWA at `http://localhost:8000/` for search/chat/playlist steps.

---

## Act 1 — Problem (30 sec)

> "I watch hours of YouTube and bookmark articles, then can't find that one video where someone explained MCP on a whiteboard. AI Memory Agent saves on purpose and lets me search by meaning — not just titles."

---

## Act 2 — Install & Trust (45 sec)

1. Show extension icon in toolbar
2. Open popup → point out:
   - API connection status
   - "Why are you saving this?" goal field (intent at capture)
   - Privacy note: nothing saved until you click Save (post V1-2: show context panel + pause)

**Say:** "No background recording. No passwords. You control what's observed."

---

## Act 3 — Instant Save on YouTube (2 min)

1. Navigate to a **short** public YouTube video (tech explainer, 5–15 min)
2. **Do not copy the URL**
3. Click extension → **Save current tab** (post V1-3: highlight auto-detected title, channel, timestamp)
4. Show immediate "Saved" + capture ID
5. Open PWA → ingest/jobs panel → show processing stages: Metadata → Transcript → Capsule → Embedding

**Say:** "Heavy work runs async. If transcript isn't available, we'll tell you — we don't pretend it was indexed."

**Fallback:** Paste URL in PWA ingest if extension save fails.

---

## Act 4 — Playlist Import (1.5 min)

1. PWA → **Capture** (`/#capture`) — or extension → **Playlist in Workspace**
2. Paste **public** playlist URL (e.g., curated "AI tools" playlist)
3. **Preview playlist:** real title + video count + sample titles
4. **Confirm import** (not one-click blind ingest)
5. Show progress card → pause → resume → retry failed (optional)

**Say:** "Bulk imports always ask before uploading. Watch Later needs Google OAuth later — today we demo with a public playlist."

**Fallback:** Pre-ingested library; skip live import. Do **not** open Watch Later or scrape private lists.

---

## Act 5 — Search (1.5 min)

1. Extension popup → **Command** bar: type `search MCP servers` → **Run** (inline results)
2. Optionally **Open in Workspace** for full cards (`#search/MCP%20servers`)
3. Show results with:
   - Title + matched snippet (popup) or thumbnail + **Why matched** (Workspace)
   - Timestamp link to jump in video (Workspace)

4. Second query: `local LLM deployment` (bare keywords → search)

**Say:** "Search uses transcripts and metadata we actually saved — not guessed visual details."

**Fallback:** PWA Search panel if extension offline.

---

## Act 6 — Chat & Synthesis (2 min)

1. Extension command: `ask Summarize what my saved videos say about RAG` → **Run**
2. Or Workspace Ask panel → same question
3. Show:
   - Grounded answer paragraph
   - Source cards / citations
   - Confidence indicator (Workspace)
   - Related recommendations (Workspace)

4. If clarification prompt appears, pick an option — show disambiguation

**Fallback:** Use deterministic (non-LLM) mode if `llm_provider=none` — explain "works offline without OpenAI."

---

## Act 7 — Intelligence & Trust (1 min)

1. Open memory detail (API docs or future UI): `GET /api/v1/memories/by-external?source_type=youtube&external_id=...`
2. Show lifecycle state (captured → trusted)
3. Show trust score breakdown
4. Mention duplicate skip on re-save

**Fallback:** Swagger UI at `/docs` for API demonstration.

---

## Act 8 — Bookmarks (45 sec) — Post V1-4 / V1-7

1. Extension command: `import bookmarks` → plan shows **Bulk: confirm required**
2. **Confirm bulk action** → bookmark panel; **Preview** then **Confirm import**
3. Show totals (duplicates skipped)

**Say:** "Bulk imports never run silently — plan, confirm, then preview."

**Fallback:** Use Import card buttons if command bar skipped.

---

## Act 9 — Close (30 sec)

> "AI Memory Agent: save from the browser, search by meaning, answers with citations. Open source on GitHub, install from Chrome Web Store."

Show: GitHub repo, extension listing (or coming soon), LinkedIn CTA.

---

## Recording Checklist

| Item | ✓ |
|------|---|
| 1080p screen capture; cursor visible | |
| Mic clear; minimize ums | |
| No real passwords/tokens on screen | |
| Use public videos only (copyright) | |
| Show failure state once (transcript missing) | |
| End card: repo URL + store link | |
| Captions for LinkedIn silent autoplay | |

---

## Demo Data Pack (Optional)

Pre-load for reliable live demo:

| Asset | Source |
|-------|--------|
| 3–5 indexed YouTube videos | MCP, RAG, local LLM topics |
| 1 public playlist | 10–20 videos, pre-job completed |
| 1 article | Post V1-5 |
| 1 GitHub repo | Post V1-6 |

Script: `scripts/seed_demo.py` (V1-9 — seeds registry rows; not a substitute for live embeddings).

---

## Known Demo Gaps (Honest Narration)

| Feature | Current gap | What to say |
|---------|-------------|-------------|
| Watch Later | No OAuth | "Use playlist URL today" |
| Trust badges in UI | API only (V1-7b / later) | Show Swagger or PWA debug |
| Cross-source chat | Improving; demo YouTube-heavy | Scope live queries to saved library |
| CWS listing live | Package ready; human upload | "Listing ready / pending review" (do not claim live until public) |
| Demo video in repo | Human recording | Record per this script; LinkedIn 2-min cut in `docs/store/LINKEDIN_LAUNCH.md` |

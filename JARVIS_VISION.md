# JARVIS VISION — AI Memory Operating System

**Purpose:** Long-term product vision focused on **user experience**, not implementation.  
**Audience:** Product, design, engineering alignment.  
**Status:** North star — many elements are **not built yet**.  
**Last updated:** 2026-07-18  
**Companion:** `MASTER_SPEC.md` (execution), `KNOWLEDGE_ENGINE.md`, `AGENT_BIBLE.md`

---

## 1. One-Sentence Vision

**Jarvis is a personal AI operating system that remembers everything you choose to save, understands why it mattered, and helps you act on it — with proof, not vibes.**

---

## 2. The User We Serve

**Primary:** Curious professionals and lifelong learners who consume video and web content faster than they can organize it.

**Secondary:** Builders and researchers who need **cited, timestamped** answers from their own corpus — not the internet's.

**Not primary (v1):** Enterprise wiki replacement, team PM, or generic note-taking without media.

---

## 3. Core Experience Pillars

### 3.1 Capture without friction

**Today (built):** Paste YouTube URLs, import playlists, save from extension, share sheet to PWA.

**Jarvis (future):** Anything worth keeping flows in with one gesture — video, article, PDF, meeting note, voice thought — without asking you to file it. The OS captures **context at save time**: *why* you saved it, *what goal* it serves.

**UX feeling:** “I threw it at Jarvis and moved on.”

---

### 3.2 Memory you can trust

**Today (built):** Search and chat return sources with YouTube timestamp links; deterministic answers when LLM is off.

**Jarvis (future):** Every answer shows **why this memory counts** — trust badge, recency, your past feedback, agreement across sources. When sources disagree, Jarvis says so plainly.

**UX feeling:** “It’s citing *my* stuff, and I can verify in one click.”

---

### 3.3 Ask anything across your life’s library

**Today (built):** Semantic search + chat over ingested YouTube library.

**Jarvis (future):** One command bar — search, ask, capture — across all connectors. “What did I learn about async Python across courses and articles?” pulls hierarchical evidence, not ten siloed apps.

**UX feeling:** “One brain for everything I’ve saved.”

---

### 3.4 Jarvis works while you sleep

**Today (built):** Background playlist jobs with pause/resume.

**Jarvis (future):** Agents triage your capture queue, retry failures, consolidate duplicates, and prepare a **morning briefing**: what to review, what’s missing for your goals, what’s new in topics you follow.

**UX feeling:** “My memory OS maintained itself overnight.”

---

### 3.5 Learn intentionally, not accidentally

**Today (built):** Reflection form at ingest; recommendations API.

**Jarvis (future):** **Reverse Memory** — Jarvis knows your goals and tells you what you *haven’t* learned yet. Spaced review from Review Agent. Gap reports that feel like a coach, not a nag.

**UX feeling:** “Jarvis knows what I’m trying to become.”

---

## 4. Day-in-the-Life (Target UX)

### Morning

You open Jarvis (PWA or desktop shell). A **briefing card** shows:

- 3 memories to review (from goals you set weeks ago)  
- 1 gap: “You’re building a home lab but never saved networking content”  
- 2 captures waiting from yesterday’s extension queue  

You tap **Review** — 60 seconds of flashcard-style prompts with “jump to moment” links.

### During work

You watch a YouTube tutorial. The extension offers **Save with goal** — you pick “Kubernetes cert” and one line of note. Jarvis ingests in background.

You share an article from phone → share sheet → Jarvis. No account friction in demo mode; sync when online.

### Afternoon

You ask: *“Compare the GPU advice from my saved build videos.”*

Jarvis returns a **consensus view**: where creators agree, where they conflict, each with timestamps. Trust badges show which memories you’ve marked helpful before.

### Evening

You start a 40-video course playlist. Jarvis estimates time, creates a **resumable job**, you pause halfway — resume tomorrow from exact position.

---

## 5. Interface Surfaces (Vision Map)

| Surface | Role | Status |
|---------|------|--------|
| **Command bar** | Unified search · ask · capture | Planned (U-01) |
| **Memory timeline** | Browse by date, goal, source | Planned (U-02) |
| **Source cards** | Video/article with reflection + trust | Partial (search cards) |
| **Job console** | Playlist progress, pause, retry | Built (PWA) |
| **Review mode** | Spaced repetition | Planned (A-04) |
| **Briefing home** | Proactive daily digest | Planned (U-03) |
| **Agent activity** | Audit trail of what Jarvis did | Planned (A-07) |
| **Connector hub** | Connect Readwise, Drive, etc. | Planned (C-02) |
| **Settings / trust** | Auth, export, delete my data | Partial |

---

## 6. Emotional Design Goals

| Emotion | How Jarvis earns it |
|---------|---------------------|
| **Relief** | Bulk ingest just works; jobs resume |
| **Trust** | Citations, verification, no mystery chat |
| **Control** | Self-host option; export everything |
| **Delight** | “You saved this for X — relevant now” |
| **Clarity** | Gaps and reverse memory feel actionable |

**Anti-goals emotionally:** Overwhelming graph views, fake “self-organizing” magic, creepy ambient recording without consent.

---

## 7. Jarvis vs Today’s Product

| Dimension | Today | Jarvis target |
|-----------|-------|---------------|
| Sources | YouTube + web capture | Universal connectors |
| Intelligence | AHME + chat | + Trust, consensus, gaps |
| Proactivity | None | Briefings, review, agents |
| Identity | Local demo user | Full auth + multi-device |
| Platform | Single-node self-host | Scalable OS, same UX |
| Voice | None | Optional capture/query |

---

## 8. Privacy & Consent UX (Non-Negotiable)

Jarvis must **never** feel like surveillance.

- Explicit save actions (extension, share, paste) — no hidden screen recording in base product.  
- Clear data map: “What Jarvis knows” settings page.  
- One-click export and delete.  
- Agents show **pending actions** before executing external or bulk writes.  
- Trust tiers visible — user knows when answer is single-source.

*(Ambient capture may be a **future optional connector** with separate consent flow — not core Jarvis.)*

---

## 9. Success Metrics (UX-Oriented)

| Metric | Meaning |
|--------|---------|
| Time to first cited answer | Onboarding success |
| Capture → ingest success rate | Pipeline reliability |
| % chats with source clicks | Trust engagement |
| Review completion rate | Memory sticks |
| Goal gap resolution rate | Reverse memory value |
| Weekly active memory queries | Habit formation |
| Export/download usage | Trust in ownership |

---

## 10. Phased UX Evolution

### Phase 1 — Reliable memory (now → near)

Polished PWA, stable ingest/search/chat, reflection at save, jobs that don’t lose progress.

*User feels:* “This actually works for my YouTube library.”

### Phase 2 — Intelligent memory

LLM synthesis optional, trust badges, better enrichment, unified command bar.

*User feels:* “Answers are better than ChatGPT for my saved stuff.”

### Phase 3 — Connected memory

Readwise bridge, articles, graph exploration, export.

*User feels:* “Everything I read is in one place.”

### Phase 4 — Agent-assisted memory

Capture triage, research reports, review mode, approval flows.

*User feels:* “Jarvis helps maintain my library.”

### Phase 5 — Full Jarvis OS

Morning briefings, learning evolution, multi-device, connector marketplace, proactive coaching.

*User feels:* “I have a personal operating system for knowledge.”

---

## 11. What Jarvis Is Not

See `MASTER_SPEC.md` § Non-Goals. Summary:

- Not a team wiki (Notion)  
- Not a markdown vault (Obsidian)  
- Not a highlight exporter only (Readwise)  
- Not a general chatbot (ChatGPT)  
- Not covert lifelogging (Rewind-class without consent)

---

## 12. Narrative Taglines (Internal)

- **“Save once. Ask forever.”**  
- **“Your memories, cited.”**  
- **“The OS for everything you learn.”**  
- **“Jarvis remembers why — not just what.”**

---

## 13. Related Documents

| Document | Focus |
|----------|-------|
| `COMPETITOR_BIBLE.md` | Market gaps Jarvis fills |
| `FEATURE_IDEAS.md` | UX feature IDs U-01–U-06 |
| `KNOWLEDGE_ENGINE.md` | How memory intelligence works |
| `AGENT_BIBLE.md` | Autonomous behaviors |
| `CONNECTOR_SDK.md` | How content enters the OS |

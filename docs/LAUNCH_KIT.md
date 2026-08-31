# AI Memory Agent — Launch Kit

This file turns product work into repeatable public distribution without inflating metrics or spamming communities.

## One-line positioning

**AI Memory Agent turns saved YouTube videos, web pages, PDFs, GitHub repos, and bookmarks into one self-hosted searchable memory with hybrid retrieval and cited answers.**

## Short description

Most saved-content tools make you remember where something was saved and roughly what it was called. AI Memory Agent is built around how people actually remember: fragments, concepts, and context. It normalizes multiple source types into one memory layer, combines dense + lexical retrieval, narrows through hierarchical memory, diversifies results with MMR, and can answer questions with citations back to saved evidence.

## Demo sequence

Keep the public demo under 60 seconds.

1. Show a YouTube/video or article with a title that does not contain the later search phrase.
2. Click **Save To Memory** from the extension.
3. Save two more related items from different sources.
4. Search using a vague conceptual memory rather than an exact title.
5. Show the correct item appearing.
6. Ask a cross-source question in **Ask Memory**.
7. Expand/show the citations.
8. End on the architecture diagram + GitHub repository.

The demo should prove one memorable idea: **you do not need to remember where you saved something or what it was called.**

## LinkedIn launch post

### Hook

I kept saving useful videos, articles and GitHub repos — and then losing them inside the apps where I saved them.

So I built a search engine for my own saved knowledge.

### Body

AI Memory Agent takes saved YouTube videos, web pages, PDFs, GitHub repos and bookmarks and turns them into one searchable memory.

The part I cared about most was retrieval quality. I did not want a thin vector-search wrapper, so the system now uses:

- hierarchical memory (capsule → section → evidence)
- dense + lexical retrieval
- Reciprocal Rank Fusion
- MMR diversification
- semantic caching
- deduplication
- grounded answers with citations
- deterministic no-LLM fallback

The goal is simple: search the way you remember something, not the way it was originally titled.

I am building this in public and would especially value feedback on retrieval quality, connectors and the self-hosted workflow.

GitHub: https://github.com/antonypaul98/ai-memory-search-agent

### Suggested visual

Use the short demo video/GIF, not a screenshot of code.

## LinkedIn technical follow-up

### Hook

Vector search alone was not enough for the personal-memory system I am building.

### Body

A personal knowledge store has a ranking problem: one saved source can contain many semantically similar chunks, so naïve vector search can return repetitive evidence and miss useful lexical matches.

The current retrieval path in AI Memory Agent combines:

1. hierarchical coarse-to-fine narrowing
2. dense embeddings
3. SQLite FTS5 lexical search
4. RRF rank fusion
5. MMR diversification
6. citation-backed synthesis

The interesting part for me has been treating retrieval as an engineering system rather than a single database query.

Architecture + code: https://github.com/antonypaul98/ai-memory-search-agent

## Show HN draft

**Title:** Show HN: AI Memory Agent – self-hosted search for saved videos, pages, PDFs and repos

I built AI Memory Agent because I had useful content saved across YouTube, bookmarks and other sources, but finding it later required remembering where it lived and what it was called.

The project normalizes saved sources into one memory layer and uses a hierarchical retrieval engine (AHME) with dense + lexical search, RRF fusion, MMR diversification, semantic cache and citation-backed answers. The LLM layer is optional; deterministic synthesis works without one.

It currently includes a FastAPI backend, Chrome MV3 extension and installable PWA workspace. It is MIT licensed and self-hostable.

I would be particularly interested in feedback on the retrieval architecture, evaluation methodology and useful next connectors.

Repository: https://github.com/antonypaul98/ai-memory-search-agent

## Reddit / community draft

I built a self-hosted search layer for the content I keep saving and forgetting.

It supports YouTube, web pages, PDFs, GitHub repos and bookmarks, and searches across them using hybrid dense + lexical retrieval rather than exact titles. There is also an Ask Memory flow that answers from retrieved evidence with citations.

I am looking for technical/product feedback rather than just stars — especially around retrieval quality, source connectors and what a useful self-hosted workflow should look like.

Repo: https://github.com/antonypaul98/ai-memory-search-agent

Before posting, adapt this to the community's rules and explain why the project is relevant there. Do not cross-post identical copy into many communities at once.

## X / short-post drafts

### Product

I built a search engine for everything I keep saving and forgetting.

YouTube + web + PDFs + GitHub + bookmarks → one self-hosted memory.

Search by how you remember it, then ask questions with citations back to the saved evidence.

https://github.com/antonypaul98/ai-memory-search-agent

### Technical

Personal memory retrieval > one vector query.

Current stack in AI Memory Agent:
- hierarchical narrowing
- dense + FTS5
- RRF
- MMR
- semantic cache
- dedup
- cited synthesis

MIT / self-hosted:
https://github.com/antonypaul98/ai-memory-search-agent

## Content series

Instead of one launch, publish a sequence where each post teaches one thing:

1. The saved-content retrieval problem
2. Why vector search alone was not enough
3. RRF + MMR in a personal-memory system
4. Building universal source connectors
5. Grounded answers and deterministic no-LLM fallback
6. Privacy / tenant isolation lessons
7. AHME benchmark methodology
8. Building the browser capture workflow
9. Knowledge graph / memory intelligence evolution
10. What failed and what changed after user feedback

Each post should contain one useful idea even if the reader never clicks the repository.

## Repository discovery checklist

Repository settings that should be maintained:

- concise description with the user problem + differentiation
- homepage pointing to a real demo when available
- relevant GitHub topics
- Issues enabled
- Discussions enabled once there is enough traffic to sustain them
- social preview image
- pinned release / changelog when public releases begin

Suggested GitHub topics:

`ai-memory`, `rag`, `semantic-search`, `hybrid-search`, `vector-search`, `second-brain`, `personal-knowledge-management`, `self-hosted`, `fastapi`, `chromadb`, `browser-extension`, `knowledge-graph`, `llm`, `retrieval-augmented-generation`

## What not to do

Do not buy or script fake stars, watchers, forks, issue activity, clones, or page views. Do not create sock-puppet accounts or star-exchange rings. Those numbers do not create users, can damage credibility, and make later conversion metrics meaningless.

Automation is useful for **distribution**, not fake engagement: scheduled release posts, changelog generation, demo refreshes, benchmark publishing, community-specific launch reminders and tracking which real channels generate meaningful visitors.

## Metrics that matter

Track a funnel rather than raw view counts:

```text
impressions
  → repository visits
  → README/demo engagement
  → stars
  → successful local runs
  → issues/discussions
  → repeat contributors
```

For career visibility, also track whether the project generates recruiter messages, technical conversations, profile follows, interview discussions, or references from other repositories/posts.

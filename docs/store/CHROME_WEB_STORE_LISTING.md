# Chrome Web Store — Listing Package (V1-9)

**Status:** **Ready to submit** — package complete in-repo. **Not submitted** from this environment (requires Chrome Web Store Developer Dashboard + human screenshots).  
**Privacy policy:** Backend serves `/privacy` (V1-8). Point the CWS privacy field at your hosted origin + `/privacy`.  
**Version:** Must match [`VERSION`](../../VERSION) and `extension/manifest.json` (**1.9.0**).

---

## Submission honesty

| Claim | Truth |
|-------|--------|
| Listing copy + permission justifications | Ready in this file |
| Icons 16 / 48 / 128 | Ready (`extension/icons/`) |
| Promo tile 440×280 + marquee 1400×560 | Generated (`docs/store/assets/`) |
| Screenshots | **Placeholders only** — replace with real captures before upload |
| Live CWS listing URL | **Not published** — human upload required |
| Privacy URL | Ready when backend is hosted (`{origin}/privacy`) |

---

## Listing fields

| Field | Value |
|-------|-------|
| **Name** | AI Memory Agent |
| **Short description** (132 chars max) | Save YouTube, pages, bookmarks & PDFs to Memory. Search by meaning. Ask with citations — you control what is saved. |
| **Category** | Productivity |
| **Language** | English |
| **Icon** | `extension/icons/icon-128.png` (also 16 / 48) |
| **Version** | `1.9.0` (from `VERSION`) |
| **Privacy policy URL** | `https://{your-host}/privacy` (local demo: `http://127.0.0.1:8000/privacy`) |

### Detailed description

AI Memory Agent turns what you intentionally save into a searchable personal knowledge library.

**What you can do**
- Observe the current tab (YouTube or web) and **Save To Memory** without copying URLs
- Run commands from the popup: `search …`, `ask …`, `import bookmarks`, `import playlist`, `help`
- Import bookmarks and PDFs with **preview → confirm** (no silent bulk upload)
- Open the AI Memory Workspace (PWA) for full search, Ask Memory, playlists, and imports

**What we do not do**
- No covert recording or keylogging
- No password / payment field capture
- Incognito is not supported in V1
- Watch Later requires Google OAuth later — demos use a **public playlist URL**

Backend runs on your machine (or your host). The extension talks to your configured API base (default `http://127.0.0.1:8000/api/v1`).

---

## Assets checklist

| Asset | Location | Status |
|-------|----------|--------|
| Icon 16 / 48 / 128 | `extension/icons/` | Ready |
| Promo tile 440×280 | `docs/store/assets/promo-small-440x280.png` | Ready (generated) |
| Marquee 1400×560 | `docs/store/assets/marquee-1400x560.png` | Ready (generated, optional) |
| Screenshots (1–5) | `docs/store/assets/screenshot-*-placeholder.png` | **Replace before upload** |
| Privacy policy URL | `{backend}/privacy` | Served by FastAPI |
| CWS disclosure text | `app/static/privacy-disclosure.txt` | Ready |
| ZIP of `extension/` | Build locally (see checklist) | Human step |

### Screenshot shot list (capture before upload)

1. Popup — Currently Observing + Ready to Save (YouTube)
2. Popup — Command bar with search results
3. Popup — Bookmark import preview → confirm
4. Workspace — Universal search with why-matched
5. Workspace — Ask Memory with citations

Regenerate branded tiles: `python scripts/generate_store_assets.py`

---

## Permission justifications (CWS form)

| Permission | Justification |
|------------|---------------|
| `storage` | Settings, temporary observe context, capture IDs |
| `activeTab` / `tabs` | Read active tab metadata when user opens popup or saves |
| `contextMenus` | “Add to Memory” on page/link/selection |
| `alarms` | Expire temporary context |
| `bookmarks` (optional) | User-initiated bookmark import with preview |
| `notifications` (optional) | Optional completion alerts |
| Host access | Localhost by default; optional broader hosts only to reach user’s backend |

---

## Single-purpose statement

This extension helps users intentionally save browsed knowledge into a personal Memory backend, then search and ask questions over that library. It does not inject ads, mine browsing history in the background, or transfer data to third parties beyond the user-configured API endpoint.

---

## Packaging steps (human)

1. Confirm `VERSION` == `extension/manifest.json` version.
2. Replace placeholder screenshots with real captures from `docs/V1_DEMO_SCRIPT.md`.
3. Zip the `extension/` directory (no parent folder junk, no `.DS_Store`).
4. Chrome Web Store Developer Dashboard → New item → upload ZIP.
5. Paste listing fields from this doc; set privacy URL to hosted `/privacy`.
6. Attach promo tile + screenshots; submit for review.

See also: `docs/store/SUBMISSION_CHECKLIST.md`, `docs/V1_9_DEMO_STORE_LAUNCH.md`.

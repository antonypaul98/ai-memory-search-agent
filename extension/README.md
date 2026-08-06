# AI Memory Agent — Chrome Extension (Manifest V3)

The Chrome extension is the **interface** for the AI Memory Agent. The FastAPI backend is the intelligence platform.

## Load in developer mode

1. Start the backend:

```bash
source .venv_clean/bin/activate
JOBS_ENABLED=true AUTH_ENABLED=false PWA_ENABLED=true \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

2. Open `chrome://extensions`
3. Enable **Developer mode**
4. **Load unpacked** → select this `extension/` folder
5. Open any YouTube video → click the toolbar icon

You should see **Currently Observing** with video details (no URL copy required).

## Permissions

| Permission | Why |
|------------|-----|
| `storage` | Settings + temporary session context |
| `activeTab` / `tabs` | Read active tab for save & observe |
| `contextMenus` | “Add to Memory” on page/link/selection |
| `alarms` | Expire temporary context |
| `bookmarks` (optional) | Import bookmarks (preview → confirm) into Memory |
| `notifications` (optional) | Completion alerts |

Incognito is **not allowed** in V1.

## Privacy

- Temporary context is held in session storage and expires (~30 minutes).
- Nothing is written into Memory until you press **Save To Memory**.
- Passwords, payment fields, and form inputs are never read.
- **Pause Observation** / **Clear Temporary Context** are available in the popup.
- Hosted privacy policy (when backend is running): `{backend_origin}/privacy`
- Export / delete Memory data via Workspace **Settings** or:
  - `GET /api/v1/privacy/export`
  - `DELETE /api/v1/memories/{id}`
- Auth: when `AUTH_ENABLED=true`, use register/login; `POST /api/v1/auth/logout` revokes the session.

See `docs/V1_PRIVACY_MODEL.md` and `docs/V1_8_AUTH_PRIVACY.md`.

## Command bar (V1-7)

Popup **Command** input (focused on open). Examples:

| Command | Behavior |
|---------|----------|
| `search MCP servers` | Hybrid search; inline results |
| `ask what did I learn about RAG` | Grounded chat; inline answer |
| `save` | Handoff to **Save To Memory** |
| `import bookmarks` | Plan → **Confirm bulk** → preview→confirm |
| `import playlist` | Plan → confirm → Workspace `#capture` |
| `help` | Lists supported commands |

Keyboard: **Ctrl+Shift+M** / **⌘⇧M** opens the popup (`manifest.commands`).

Bulk intents call `POST /api/v1/agent/command` and require a `confirm_token` — never silent multi-item writes.

See `docs/V1_7_AGENT_COMMAND.md` and store package `docs/store/CHROME_WEB_STORE_LISTING.md` (V1-9 — ready to submit; not auto-uploaded). Manifest version **1.9.0**.

## Workspace (V1-5)

Open the PWA at your backend root (`http://127.0.0.1:8000/`) for the full **AI Memory Workspace**:

- Dashboard · Universal search · Ask Memory · Timeline · Topics · Imports · Capture · Settings

Popup **Ask My Memory** / **Search Memory** use the command input when filled; otherwise open `{pwa_url}#ask` / `#search`.  
Deep-links with query: `#search/<urlencoded>` · `#ask/<urlencoded>`.  
Popup **Playlist in Workspace** opens `{pwa_url}#capture` (deep-link only; no Watch Later scrape).

See `docs/V1_5_MEMORY_WORKSPACE.md` and `docs/V1_6_PLAYLIST_WATCH_LATER.md`.

## Import (V1-6)

Popup **Import** section:

| Action | Behavior |
|--------|----------|
| **Import bookmarks** | Requests optional `bookmarks` permission → preview → confirm → `POST /capture/bookmarks/*` |
| **Upload PDF** | Multipart `POST /capture/pdf` |
| **Playlist in Workspace** | Opens `{backend}/#capture` (full preview→confirm→job UI) |

**Watch Later:** Coming soon (Google OAuth). Do not scrape. Demo with a **public playlist URL** in Workspace Capture.

See `docs/V1_6_PLAYLIST_WATCH_LATER.md`.

## Settings

Right-click the extension icon → **Options**, or use the ⚙ button in the popup.

Configure backend URL, theme, privacy mode, notifications, and debug mode.

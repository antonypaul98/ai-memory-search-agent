# AI Memory Agent

**Version 1.9.0** — intentionally save YouTube, web pages, bookmarks, and PDFs into a personal Memory you can search by meaning and ask with citations.

Self-hosted FastAPI backend + Chrome extension (MV3) + AI Memory Workspace (PWA).

> **V1 status:** Track complete (V1-0 … V1-9). Chrome Web Store package is **ready to submit** (not auto-uploaded from CI). See [`docs/V1_9_DEMO_STORE_LAUNCH.md`](docs/V1_9_DEMO_STORE_LAUNCH.md).

---

## What you can do

- **Observe & save** the current tab (no URL copy) with explicit Save
- **Command bar:** `search …`, `ask …`, `import bookmarks`, `import playlist`, `help`
- **Workspace PWA:** dashboard, universal search, Ask Memory, playlists, imports, privacy controls
- **Trust & lifecycle** on saved memories (API + demo via Swagger)
- **Export / delete** your data when auth/privacy controls are enabled

## What we do not do (V1)

- Covert recording, keylogging, or password capture
- Incognito support
- Watch Later via Google OAuth (use a **public playlist URL** for demos)
- Version 2 engines (Ontology, Consensus/Gap, multi-agent marketplace)

---

## Quick start

Use **Python 3.11**. Prefer a clean venv (this repo uses `.venv_clean` in docs/CI notes).

```bash
python3.11 -m venv .venv_clean
source .venv_clean/bin/activate
pip install -r requirements.txt
cp .env.example .env

JOBS_ENABLED=true AUTH_ENABLED=false PWA_ENABLED=true \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

| Surface | URL |
|---------|-----|
| Workspace PWA | http://localhost:8000/ |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |
| Privacy | http://localhost:8000/privacy |

### Chrome extension

1. `chrome://extensions` → Developer mode → **Load unpacked** → select `extension/`
2. Popup → API base `http://127.0.0.1:8000/api/v1`
3. Open a YouTube video → **Save To Memory**

Details: [`extension/README.md`](extension/README.md)

### Demo seed (optional)

```bash
python scripts/seed_demo.py
```

Full recording script: [`docs/V1_DEMO_SCRIPT.md`](docs/V1_DEMO_SCRIPT.md)

---

## Tech stack

| Layer | Tool |
|-------|------|
| API | FastAPI |
| Vectors | ChromaDB (persistent) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`) |
| Registry | SQLite |
| Extension | Chrome MV3 |
| Workspace | Static PWA (`app/static`) |

---

## Tests & CI

```bash
source .venv_clean/bin/activate
pytest -q
```

GitHub Actions runs `pytest -q` on push/PR (`.github/workflows/ci.yml`).

---

## Store & launch

| Artifact | Location | Status |
|----------|----------|--------|
| CWS listing package | [`docs/store/CHROME_WEB_STORE_LISTING.md`](docs/store/CHROME_WEB_STORE_LISTING.md) | Ready to submit |
| Store assets | [`docs/store/assets/`](docs/store/assets/) | Promo ready; screenshots need real captures |
| LinkedIn copy | [`docs/store/LINKEDIN_LAUNCH.md`](docs/store/LINKEDIN_LAUNCH.md) | Ready to post |
| Security policy | [`SECURITY.md`](SECURITY.md) | Published in-repo |

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`MASTER_SPEC.md`](MASTER_SPEC.md) | Canonical execution inventory |
| [`docs/V1_RELEASE_PLAN.md`](docs/V1_RELEASE_PLAN.md) | V1-0 … V1-9 phases |
| [`docs/V1_PRODUCT_SPEC.md`](docs/V1_PRODUCT_SPEC.md) | Product scope |
| [`docs/V1_PRIVACY_MODEL.md`](docs/V1_PRIVACY_MODEL.md) | Privacy model |
| [`docs/V1_9_DEMO_STORE_LAUNCH.md`](docs/V1_9_DEMO_STORE_LAUNCH.md) | Final V1 milestone |

Suggested GitHub topics: `chrome-extension`, `fastapi`, `memory`, `rag`, `chromadb`, `personal-knowledge-management`, `youtube`.

---

## License

MIT — see [`LICENSE`](LICENSE).

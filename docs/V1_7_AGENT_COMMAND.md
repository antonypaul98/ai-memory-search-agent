# V1-7 — Agent Command Polish / Store Prep

**Status:** Complete (production audit 2026-07-29)  
**Last updated:** 2026-07-29  
**Canonical scope:** MASTER_SPEC §0.7 / §12 (prefer over optional V1-7b polish).

---

## 1. Goals

1. **Extension command / search-chat UX** — popup command bar; classify → plan → safe execute; Search / Ask shortcuts  
2. **Bulk confirm patterns** — bookmarks / playlist never silent-write; `confirm_token` gate + existing preview→confirm handoff  
3. **Store packaging prep** — listing draft, icons present, keyboard command; **not** CWS submission (V1-9)  
4. **Demo alignment** — script steps reference command bar for V1-9 recording  

**Out of scope:** V1-8 auth/privacy hardening; V1-9 store submit / demo video; V1-7b trust badges / learning path / KG panels; Consensus/Gap/Agents; Watch Later OAuth.

---

## 2. Architecture

```
Extension popup command bar
        │
        ▼
 POST /api/v1/agent/command
        │  rule-based CommandRouterService
        ▼
 Plan JSON (intent · steps · confirm_token?)
        │
        ├── safe: search / ask / help  → execute via SearchService / ChatService
        ├── save                       → handoff to Save To Memory
        └── bulk: bookmarks / playlist → confirm_token required
                                              │
                                              ▼
                                    POST /api/v1/agent/command/execute
                                              │  consume (single-use) token
                                              ▼
                                    handoff → Workspace #imports / #capture
                                    (existing preview → confirm APIs)
```

Not an autonomous multi-agent runtime. Classifier is deterministic (regex/rules). Do not market as unsupervised agent in CWS.

---

## 3. APIs

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/agent/status` | Unchanged (V1-1) |
| POST | `/api/v1/agent/command` | Plan; `execute=true` runs safe intents; bulk needs `confirm_token` |
| POST | `/api/v1/agent/command/execute` | Execute planned intent; bulk blocked without valid **unused** token |

### Intents

| Intent | Auto-execute | Confirm |
|--------|--------------|---------|
| `search` | Yes (hybrid search) | No |
| `ask` | Yes (grounded chat) | No |
| `save` | Handoff to extension save | No |
| `import_bookmarks` | Handoff after confirm | **Yes** |
| `import_playlist` | Handoff to `#capture` after confirm | **Yes** |
| `open_workspace` | Handoff URL | No |
| `help` | Returns help text | No |

### Confirm token security

- HMAC-SHA256 over `user_id|intent|query_hash|exp` (TTL default **600s**)
- Prefer `AUTH_SECRET`; else random secret file beside SQLite (`.agent_confirm_secret`), not derivable from app name alone
- **Single-use:** successful bulk execute consumes the token (replay → `confirm_required`)
- Successful responses clear `plan.confirm_token` so clients cannot reuse the payload
- Confirmed bulk **never** writes — only Workspace preview→confirm handoff
- Command text is never passed to a shell; search/ask use parameterized service APIs

---

## 4. Extension UX

- Command card at top of popup (focused on open)
- **Run** → plan + inline search/ask results when executed (in-flight guard against duplicate submits)
- **Confirm bulk action** → validates + consumes token, then opens bookmark panel or Workspace Capture
- **Search Memory** / **Ask My Memory** — use command input when filled; else deep-link `#search` / `#ask`
- Keyboard: `Ctrl/Cmd+Shift+M` opens popup (`commands._execute_action`)
- Manifest version was **1.3.0** at V1-7 close; V1-9 ship version is **1.9.0** (`VERSION`)
- Command hint / plan / results use `aria-live="polite"`

Workspace deep-links: `#search/<urlencoded>` and `#ask/<urlencoded>` prefill and run (malformed `%` sequences are tolerated).

---

## 5. Store prep (not submission)

See `docs/store/CHROME_WEB_STORE_LISTING.md`:

- Name, short/long description drafts  
- Permission justifications  
- Icon paths (`extension/icons/`)  
- Screenshot shot list for V1-9  

Privacy policy page and CWS form upload remain V1-8 / V1-9.

---

## 6. Tests

| File | Coverage |
|------|----------|
| `tests/test_command_router.py` | Classification, HMAC forge/expiry/query mismatch, single-use consume, bulk gate, API plan/execute/replay |

---

## 7. Acceptance

- [x] Command bar classifies search/ask/save/import/help  
- [x] Bulk import blocked without `confirm_token`  
- [x] Confirmed bulk does not skip preview (handoff only)  
- [x] Confirm tokens are single-use within TTL; not forgeable without secret  
- [x] Store listing draft + icons documented  
- [x] Demo script references command bar  
- [x] `pytest -q` green  

---

## 8. Production audit notes (2026-07-29)

Hardened during V1-7 audit: single-use consume, non-deterministic local secret, padding-tolerant decode, execute path does not re-issue tokens on success, extension duplicate-submit guard, PWA deep-link decode safety, request field length limits.  
**V1-8 not started** (multi-user auth isolation, privacy policy page, CWS submission remain later).

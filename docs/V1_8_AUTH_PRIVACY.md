# V1-8 — Authentication, Isolation, Security, and Privacy

**Status:** Complete  
**Last updated:** 2026-07-30  
**Canonical scope:** MASTER_SPEC §0.7 / §12 (prefer over optional OAuth stubs in older release-plan rows).

---

## 1. Goals

1. **Auth integration** — register / login / me / logout with session revoke when `AUTH_ENABLED=true`
2. **Tenant hardening** — composite `(user_id, video_id)` registry keys (schema v9); memory/job isolation tests
3. **Export / delete** — JSON export + hard-delete memory APIs + thin Workspace UI
4. **Rate limiting** — in-process sliding window → HTTP 429 (P-02)
5. **Privacy policy page** — hosted `/privacy` + CWS disclosure text (store package completed in V1-9)

**Out of scope for V1-8:** Demo video / CWS Dashboard upload / LinkedIn publish (V1-9 materials); OAuth adapter framework (C-02); Watch Later production OAuth; Consensus/Gap/Agents; Enterprise RBAC; Postgres.

---

## 2. Architecture

```
Extension / PWA
      │ Bearer or session cookie
      ▼
 get_current_user ──► AuthStore (users, sessions)
      │
      ├── Memory / search / jobs  (user_id scoped)
      ├── PrivacyService.export / delete
      └── RateLimitMiddleware (per IP / token hint)
```

Demo mode (`auth_enabled=false`) continues to use `local-default` without credentials.

---

## 3. APIs

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/auth/me` | Existing |
| POST | `/api/v1/auth/register` | Existing; 403 when auth off |
| POST | `/api/v1/auth/login` | Existing; 403 when auth off |
| POST | `/api/v1/auth/logout` | **New** — revoke session + clear cookie |
| DELETE | `/api/v1/memories/{memory_id}` | **New** — hard delete (user-scoped) |
| GET | `/api/v1/privacy/export` | **New** — JSON export (`?download=true` attachment) |
| DELETE | `/api/v1/privacy/memories` | **New** — delete all memories for current user |
| GET | `/privacy` | **New** — HTML privacy policy |
| GET | `/static/privacy-disclosure.txt` | **New** — CWS disclosure draft text |

---

## 4. Schema

- **v9:** `video_registry` / `video_reflection` primary key `(user_id, video_id)`
- Migration copies existing rows; duplicate `(user_id, video_id)` kept via `INSERT OR IGNORE`

---

## 5. Rate limiting

| Setting | Default |
|---------|---------|
| `RATE_LIMIT_ENABLED` | `true` |
| `RATE_LIMIT_REQUESTS` | `120` / window |
| `RATE_LIMIT_WINDOW_SEC` | `60` |
| `RATE_LIMIT_AUTH_REQUESTS` | `20` / window (login/register) |

Keys are **per client IP** (`api:{host}` / `auth:{host}`). Bearer/cookie prefixes are intentionally *not* part of the key (rotating forged tokens must not reset the window). In-process only — not shared across multiple workers.

Static `/privacy`, `/static/*`, and non-API paths are exempt. Tests disable rate limiting via `rate_limit_enabled=False`.

---

## 6. Workspace UI

- Memory detail: **Delete memory**
- Settings → Backend: **Log out / revoke session** (clears `am_token` + `POST /auth/logout`)
- Settings → Privacy: **Export my data**, **Delete all memories**, link to `/privacy`

---

## 7. Session / cookie notes

- Session cookie: `HttpOnly`, `SameSite=Lax`, `Secure` when not `debug`/`local_demo_mode`, `Max-Age` from `session_ttl_hours`
- Logout revokes the presented Bearer/cookie token and clears the cookie
- Expired session rows are deleted on `resolve_token`
- Hard-delete skips shared `memory_capsules_json` / FTS / hierarchical rows when another tenant still owns the same `external_id`

---

## 8. Tests

`tests/test_v1_8_auth_privacy.py` — auth flow, logout/expiry, registry isolation, export/delete, shared-capsule safety, 429 + token-rotation bypass, privacy page, schema v9 migration from legacy PK.

---

## 9. Exit criteria

- [x] Two users cannot see / delete each other's memories  
- [x] Export / delete documented  
- [x] Privacy policy page served  
- [x] Rate limit returns 429 (IP-keyed; no token-prefix bypass)  
- [x] Privacy/CWS disclosure ready for V1-9 store package  

See `docs/V1_PRIVACY_MODEL.md` and `docs/store/CHROME_WEB_STORE_LISTING.md` (V1-9 package complete).

**Production audit (2026-07-30):** remediations for capsule cross-tenant delete, rate-limit keying, cookie Secure/Max-Age, expired-session cleanup, email validation, Workspace logout, schema v9 PK detection (`PRAGMA` name column).

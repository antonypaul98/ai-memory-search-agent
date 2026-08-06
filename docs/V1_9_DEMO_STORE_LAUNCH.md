# V1-9 — Demo Polish, GitHub, Chrome Store, and LinkedIn Launch

**Status:** Complete (package & docs) — 2026-07-30  
**Canonical scope:** MASTER_SPEC §0.7 / §12  
**Product version:** `1.9.0` ([`VERSION`](../VERSION) ↔ `extension/manifest.json`)

---

## 1. Goals

1. **Demo readiness** — script + seed helper for reliable local/recording demos  
2. **GitHub / README polish** — accurate V1 product surface (not stale Phase-2 scaffold)  
3. **Chrome Web Store package** — listing copy, assets, privacy URL, submission checklist (**ready to submit**, not auto-uploaded)  
4. **LinkedIn launch notes** — post copy + 2-min clip outline  
5. **CI** — GitHub Actions `pytest -q` (P-05)  
6. **SECURITY.md** — vulnerability reporting + V1 security model pointer  

**Out of scope (Version 2 / frozen):** Ontology, Consensus/Gap/Agents, Watch Later production OAuth, enterprise RBAC/MCP/multi-tenancy marketplace, live CWS Developer Dashboard upload from CI.

---

## 2. Deliverables

| Item | Path | Status |
|------|------|--------|
| Demo script | `docs/V1_DEMO_SCRIPT.md` | Ready |
| Demo seed | `scripts/seed_demo.py` | Ready |
| Store asset generator | `scripts/generate_store_assets.py` | Ready |
| Promo / placeholder screenshots | `docs/store/assets/` | Promo ready; screenshots placeholder |
| Listing package | `docs/store/CHROME_WEB_STORE_LISTING.md` | Ready to submit |
| Submission checklist | `docs/store/SUBMISSION_CHECKLIST.md` | Ready |
| LinkedIn notes | `docs/store/LINKEDIN_LAUNCH.md` | Ready to post |
| CI workflow | `.github/workflows/ci.yml` | Ready |
| Security policy | `SECURITY.md` | Ready |
| README rewrite | `README.md` | Ready |
| Version pin | `VERSION` + manifest `1.9.0` | Consistent |
| Behavioral tests | `tests/test_v1_9_release.py` | Ready |

---

## 3. Honesty matrix

| Claim | In-repo truth |
|-------|----------------|
| Version 1 track complete | Yes (V1-0 … V1-9) |
| Local / demo release ready | Yes |
| CWS listing **package** ready | Yes |
| CWS listing **live / submitted** | No — human Dashboard step |
| Demo **video file** in repo | No — human recording per script |
| LinkedIn **post published** | No — copy ready |

---

## 4. Acceptance

- [x] Demo script + seed script  
- [x] README / GitHub polish + MIT license present  
- [x] CWS listing package + privacy URL documented  
- [x] LinkedIn launch notes  
- [x] CI runs `pytest -q`  
- [x] SECURITY.md  
- [x] Version consistency (`VERSION` ↔ manifest)  
- [x] Behavioral tests for gated artifacts  
- [x] Version 2 not started  

---

## 5. Production audit (2026-07-30)

| Finding | Severity | Resolution |
|---------|----------|------------|
| Stale README (Phase 2 / Streamlit) | High | Rewrote `README.md` for V1 ship |
| No CI workflow (P-05) | High | Added `.github/workflows/ci.yml` |
| No SECURITY.md | Medium | Added `SECURITY.md` |
| Version drift (manifest 1.3.0 vs ship) | Medium | `VERSION` + manifest **1.9.0** + CI check |
| CWS promo assets missing | Medium | Generated via `scripts/generate_store_assets.py` |
| Screenshot placeholders could be uploaded by mistake | Medium | Filenames `*-placeholder.png` + checklist + assets README |
| Short description length | Low | 115 chars (≤132) — gated by test |
| Privacy URL for CWS | Low | `/privacy` still served — gated by test |
| Hosted Fly/Railway demo | Low | Deferred (optional); local demo path documented |
| Live CWS / LinkedIn / video binary | Info | Explicitly human steps; docs say “ready” not “live” |

**Fixes applied during audit:** VERSION sync, CI workflow, SECURITY.md, README rewrite, store assets, privacy-model/V1-7/V1-8/V1-product-spec status sync, U-06 deferred to post-V1 (not claimed as V1-9 UI work).

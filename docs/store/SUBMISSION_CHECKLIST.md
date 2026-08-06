# Chrome Web Store — Submission Checklist (V1-9)

**Goal:** Publish (or unlisted publish) AI Memory Agent from a complete in-repo package.  
**Environment note:** This repo prepares the package; the Developer Dashboard upload is a **human** step.

## Pre-flight

- [ ] `VERSION` matches `extension/manifest.json` (`1.9.0`)
- [ ] Backend `/privacy` reachable on the URL you will paste into CWS
- [ ] `app/static/privacy-disclosure.txt` reviewed
- [ ] Icons present: `extension/icons/icon-{16,48,128}.png`
- [ ] Promo tile present: `docs/store/assets/promo-small-440x280.png`
- [ ] Real screenshots (not `*-placeholder.png`) attached — at least 1, prefer 5
- [ ] Permission justifications copied from `CHROME_WEB_STORE_LISTING.md`
- [ ] Single-purpose statement reviewed
- [ ] No secrets in extension package (no `.env`, no API keys in source)
- [ ] Incognito: not allowed (already set in manifest)
- [ ] Demo script dry-run once (`docs/V1_DEMO_SCRIPT.md`)

## Package

```bash
# from repo root
cd extension && zip -r ../ai-memory-agent-1.9.0.zip . -x '*.DS_Store' -x 'tests/*' -x 'package.json'
```

## Dashboard

- [ ] Upload ZIP
- [ ] Paste short + detailed description
- [ ] Set category Productivity / language English
- [ ] Privacy policy URL → `https://{host}/privacy`
- [ ] Upload icons / promo / screenshots
- [ ] Submit for review **or** save as draft / unlisted

## After submit

- [ ] Record listing URL (or “pending review”) in release notes
- [ ] Do **not** claim “available on Chrome Web Store” until live
- [ ] LinkedIn post can say “listing submitted / coming soon” until approved

## Intentionally deferred

- Watch Later Google OAuth verification
- Paid listing features
- Enterprise distribution / force-install policies

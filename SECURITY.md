# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.9.x (V1 ship) | Yes |
| < 1.9 | Best-effort (self-hosted) |

Product version is defined in [`VERSION`](VERSION) and must match `extension/manifest.json` `version`.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security-sensitive reports.

1. Email the maintainer listed in the GitHub repository profile, **or**
2. Open a private security advisory on GitHub (Security → Advisories → New draft advisory) if enabled.

Include: affected component (API / extension / PWA), version (`VERSION` or commit SHA), reproduction steps, and impact.

We aim to acknowledge reports within **7 days** and share a remediation plan when confirmed.

## Security model (V1)

- **Self-hosted by default.** The Chrome extension talks only to the user-configured API base URL.
- **No covert capture.** Observation is temporary and on-device; Memory writes require explicit Save / confirmed import.
- **Auth optional.** When `AUTH_ENABLED=true`, sessions are required; tenants are isolated by `user_id`.
- **Rate limiting.** Sliding-window limits apply to API routes (see `docs/V1_8_AUTH_PRIVACY.md`).
- **Secrets.** Never commit `.env`, `AUTH_SECRET`, or production credentials. Use `.env.example` as a template only.

## Out of scope for V1

- Enterprise RBAC / SSO / multi-region tenancy
- Chrome Web Store OAuth verification for private YouTube playlists (Watch Later)
- Guaranteed multi-worker rate-limit coordination (in-process limiter only)

See also: [`docs/V1_PRIVACY_MODEL.md`](docs/V1_PRIVACY_MODEL.md), [`/privacy`](app/static/privacy.html) when the backend is running.

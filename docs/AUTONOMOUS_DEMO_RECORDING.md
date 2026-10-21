# Autonomous browser acceptance and screen recording

Workflow: .github/workflows/browser-demo-recording.yml

This job runs the **real FastAPI Memory Agent** against disposable SQLite
and Chroma stores, creates **real sentence-transformer embeddings** for
clearly labeled synthetic source passages, and drives the actual PWA UI
in **Chromium** with Playwright. The recording is real browser footage, not
a slideshow, a fabricated demo, a mock API response or generated artwork.

The test runs automatically on pushes to codex/demo-e2e-recording.
After the workflow is incorporated into main, it can be run again in
GitHub Actions using **Run workflow**. No human clicks are needed inside
the app. The job fails if a required test or screen recording fails.

## Artifacts

Actions -> Memory Agent browser demo and recording -> latest run ->
Artifacts -> download memory-agent-real-browser-demo-<run-id>.

Inside the ZIP:
- memory-agent-browser-demo.webm — real Chromium video.
- screenshots/01...04 — browser screenshots, one per UI section.
- results.json and RESULTS.md — each pass/fail gate.
- server.log — logs of the running FastAPI process.

The job uploads available artifacts even if an assertion fails.

## Verified scope when green

1. Backend readiness.
2. Real search engine returns persisted fixture vectors.
3. UI Search shows the matched evidence.
4. UI opens its stored source detail.
5. Backend chat produces a grounded answer with cited source ID.
6. UI Ask displays the cited answer/evidence, and an actual video is saved.

Fixture titles start with TEST DATA. No personal saved videos or third-party
accounts are used. The job intentionally selects the supported **flat**
retrieval pipeline for deterministic isolated verification, not the full
hierarchical engine.

## Explicitly not verified by this test

- Real YouTube transcript download or live video imports.
- Private Watch Later/Google OAuth.
- Extension installation on the user's computer.
- Full hierarchical AHME retrieval and live LLM providers.
- Physical Mac camera/desktop hardware or its permissions.
- A running public deployment.

Those are independent end-to-end gates. Never label those as passed
based on a passing synthetic-fixture browser recording.

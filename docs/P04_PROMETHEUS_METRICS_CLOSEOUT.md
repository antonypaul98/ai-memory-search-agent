# P-04 Structured Metrics (Prometheus) — Acceptance Closeout Candidate

Status: implementation complete on this branch; full repository CI required before promotion.

## Documented acceptance

`FEATURE_IDEAS.md` defines P-04 as structured Prometheus metrics with a `/metrics` endpoint.

## Implemented behavior

- `GET /api/v1/metrics` now emits Prometheus 0.0.4 text exposition.
- Existing process-local counters remain the source of truth; no new persistence, network dependency, or background worker is introduced.
- The previously available JSON snapshot is retained at `GET /api/v1/metrics.json` for compatibility.
- Metrics expose only aggregate counters plus bounded labels: HTTP status code and a fixed allowlist of tracked route names.
- User IDs, questions, answers, URLs, titles, request IDs, tokens, and other private memory content are never emitted as metric labels or values.

## Exposed metric families

- completed HTTP requests;
- in-flight HTTP requests;
- average request duration;
- response totals by status code;
- bounded search/chat route latency count, average, and p95;
- aggregate chat totals, clarification totals, grounded totals, and grounded rate.

## Regression coverage

`tests/test_observability.py` verifies:

1. `/metrics` uses Prometheus text exposition;
2. required metric families and bounded labels are present;
3. request identifiers and private-field names are absent from exposition;
4. `/metrics.json` preserves the prior JSON snapshot contract;
5. existing request-ID safety behavior remains covered.

## Scope

This closes only the documented single-process Prometheus endpoint acceptance. Distributed metric aggregation, external Prometheus deployment, dashboards, alerting, and Jarvis-specific telemetry remain outside this feature unless separately promoted.

# P-01 Readiness vs Liveness — Acceptance Closeout

Status: acceptance validated on existing implementation; root inventory reconciliation pending.

## Documented acceptance

`FEATURE_IDEAS.md` defines P-01 as readiness vs liveness probes with the acceptance summary `K8s-ready health split`.

## Implemented behavior

- `GET /api/v1/live` is process liveness and deliberately performs no Chroma dependency check.
- `GET /api/v1/ready` is dependency readiness and returns 503 when required Chroma storage is unavailable.
- `GET /api/v1/health` remains a backward-compatible readiness alias.

## Regression coverage

`tests/test_health.py` proves:

1. liveness remains 200 even when Chroma connection checks fail;
2. readiness is 200 when required storage is available;
3. readiness returns 503 when Chroma is unavailable;
4. the compatibility `/health` route retains the same dependency-aware behavior.

The repository CI that validated the current `main` already includes these tests. No runtime change is required to satisfy the documented P-01 acceptance boundary.

## Safety / scope

This closeout does not claim that P-04 Prometheus metrics are complete. The current `/metrics` implementation is a process-local JSON observability snapshot; `FEATURE_IDEAS.md` explicitly calls for Prometheus under P-04, so that row requires a separate implementation/acceptance audit.

No Jarvis-specific behavior is introduced by this closeout.

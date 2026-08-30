# F-27 / F-28 Ops Tooling Closeout

Status: **Complete for the documented Memory Search acceptance boundary**

This closeout reconciles two stale `MASTER_SPEC.md` / `FEATURE_IDEAS.md` rows against executable behavior already on `main`. It does not expand either feature beyond its documented acceptance criteria.

## F-27 — Benchmark & Import Diagnostics

Documented acceptance boundary:

- the AHME benchmark script produces a report;
- the previous gap was that the benchmark was not exercised by CI.

Validated implementation evidence:

- `scripts/benchmark_ahme.py` is a reproducible flat-vs-hierarchical AHME benchmark.
- It writes the benchmark report to `docs/BENCHMARK_AHME.md`.
- `.github/workflows/ci.yml` executes `python scripts/benchmark_ahme.py` as the `AHME benchmark smoke` step on every PR targeting `main`.
- The latest repository CI gate that validated the current `main` ancestry also passed that smoke step.

Acceptance result: **Complete**. The benchmark/report path and CI smoke requirement are both implemented. Additional benchmarking breadth or performance targets are future tuning, not missing F-27 acceptance.

## F-28 — CLI Utilities

Documented acceptance boundary:

- `reset_db.py` works as an operator reset utility;
- `ingest_item.py` works as an operator ingest utility.

Validated implementation evidence:

- `scripts/reset_db.py` implements dry-run discovery, explicit destructive confirmation, and refuses unsafe reset targets.
- `scripts/ingest_item.py` invokes the existing ingest service and emits structured success/failure output.
- `tests/test_cli_tools.py` covers reset dry-run/deletion, unsafe-target rejection, explicit confirmation, successful ingest, service failure, and structured exception handling.
- These tests are part of the full `pytest -q` CI gate.

Acceptance result: **Complete**. No additional CLI framework or autonomous behavior is implied.

## Platform audit note

P-04 Prometheus metrics was separately validated and merged before this closeout. P-03 is **not** closed by the existence of the Postgres job store: `MASTER_SPEC.md` GAP-02 requires the production relational system-of-record migration beyond jobs, including users/registry/FTS and eventual SQLite retirement in the production profile. That larger migration remains pending and must not be marked complete from partial Postgres coverage.

## Safety / scope

No secrets, private user data, new network side effects, autonomous writes, or mandatory AI are introduced by this closeout. No Jarvis-specific voice, vision, gesture, spatial, holographic, ambient-capture, or hardware work is authorized or started.

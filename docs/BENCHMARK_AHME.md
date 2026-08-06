# AHME Benchmark Report

Generated: 2026-07-15 02:42 UTC

Measured on local environment with seeded in-memory Chroma/SQLite data.
Median and p95 from repeated runs where enough samples were available.

## Pipeline comparison

| Metric | Flat pipeline | Hierarchical (AHME) |
| --- | --- | --- |
| Cold import (ms) | 97.29 | 0.0 |
| Warm import (ms) | 0.0 | 0.0 |
| Simple search median (ms) | 2.09 | 2.2 |
| Simple search p95 (ms) | 2.9 | 7.07 |
| Cross-video search median (ms) | 2.02 | 1.75 |
| Repeated search median (ms) | 1.87 | 1.27 |
| Chat median (ms) | 13.34 | 12.7 |
| Storage bytes | 463012 | 537868 |
| Evidence vectors | 4 | 4 |
| Capsule vectors | 0 | 4 |
| Section vectors | 0 | 4 |

## Notes

- Ingest timing for live YouTube URLs was not measured in this offline benchmark.
- LLM token usage is near-zero when `llm_provider=none` (default).
- Set `HIERARCHICAL_RETRIEVAL_ENABLED=false` to revert instantly to the flat pipeline.

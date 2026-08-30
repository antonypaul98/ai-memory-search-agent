# Contributing to AI Memory Agent

Thanks for taking the time to contribute.

The project values **small, testable improvements** over large framework rewrites. Before adding a dependency or abstraction, check whether the existing connector, retrieval, storage, API, or UI layer can be extended cleanly.

## Good contribution areas

- new source connectors
- retrieval quality and ranking experiments
- benchmark datasets and evaluation tooling
- search / Ask Memory UX improvements
- privacy and security hardening
- performance and token/cost reductions
- documentation and reproducible examples
- tests for edge cases and regressions

## Local setup

```bash
python3.11 -m venv .venv_clean
source .venv_clean/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest -q
```

Start the app:

```bash
JOBS_ENABLED=true AUTH_ENABLED=false PWA_ENABLED=true \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Contribution workflow

1. Open or choose a focused issue.
2. Create a branch from `main`.
3. Keep the change narrowly scoped.
4. Add or update tests.
5. Run the relevant tests locally.
6. If retrieval behavior changes, run the AHME benchmark.
7. Open a pull request explaining the problem, approach, verification, and trade-offs.

## Connector contributions

A connector should normalize into the shared source contract instead of creating a parallel ingest path.

Before opening a PR, confirm that the connector:

- has a stable way to identify an external item
- produces a canonical URL
- handles unavailable content gracefully
- does not leak credentials into logs or persisted metadata
- respects source terms, authentication boundaries, and rate limits
- includes tests for parsing and failure behavior

See [`CONNECTOR_SDK.md`](CONNECTOR_SDK.md).

## Retrieval / ranking changes

Please include:

- the retrieval problem being solved
- the baseline behavior
- the proposed algorithm or heuristic
- benchmark/evaluation impact
- latency/storage/token trade-offs
- a safe fallback where appropriate

Run:

```bash
python scripts/benchmark_ahme.py
```

and include relevant results in the PR when the change affects search or Ask Memory.

## Pull request checklist

- [ ] Change is focused and understandable
- [ ] Existing architecture was reused where practical
- [ ] Tests were added or updated
- [ ] `pytest -q` passes for the affected area
- [ ] Retrieval changes include benchmark evidence where relevant
- [ ] No secrets, tokens, personal data, or private URLs are committed
- [ ] New dependencies have a clear reason and compatible license
- [ ] Documentation reflects externally visible behavior

## Security

Do not open a public issue for a vulnerability that could put users at risk. Follow [`SECURITY.md`](SECURITY.md).

## License

By contributing, you agree that your contribution may be distributed under the repository's MIT license.

# Development

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "orchestrator[dev]" -e "ztp-service[dev]"
cd ui && npm install
```

Run the three processes (`make dev-api`, `make dev-ztp`, `make dev-ui`) and open
http://localhost:5173. Then `python tools/hatch_demo.py seed` and `boot-all`.

## Tests

```bash
cd orchestrator && pytest --cov=app      # 54 tests, ~90% coverage, runs in seconds
cd ztp-service && pytest                  # edge service against a mocked orchestrator
cd ui && npm test && npm run build        # vitest + strict TypeScript build
hatchctl templates lint                   # template governance
```

The orchestrator tests use a temporary SQLite file, `HATCH_EXECUTOR=inline` (pipelines run
synchronously inside the request) and the simulated fleet, so they exercise the real API,
state machine, renderer, compliance engine, git backups and driver contract end to end.

| File | Covers |
|---|---|
| `test_state_machine.py` | happy paths, terminal states, failure edges, Mermaid export |
| `test_rendering_and_compliance.py` | layering, placeholders, strict undefined, redaction, every template passes its baseline, rule types and scoping |
| `test_api_onboarding.py` | auth, push E2E, no-secret-leak, validation, duplicates, dry run, approvals and four-eyes, retry from post-checks and from push, rollback to snapshot, compliance gate, cancel, batches, CSV, report and audit, site scope, KPIs and metrics |
| `test_ztp.py` | ZTP E2E, pre-registration, service role, forged token, model mismatch, one-time tokens, reset to Day-0 |
| `test_units.py` | policy matching, password generation, IP rules, suggestions, CSV uplinks, event bus |

## Code quality

```bash
ruff check . && ruff format --check .
mypy app
```

## Adding a pipeline stage

1. Write `stage_<name>(ctx: PipelineContext) -> StageOutcome` in `core/pipeline.py`. Raise
   `StageFailed(message, details)` to fail. Use `ctx.redactor` for anything that may contain a
   secret (the engine also redacts `output`).
2. Add it to `STAGES`, `STAGE_STATE` and `HANDLERS`.
3. Make per-vendor behaviour configurable through `ctx.stage_spec("<name>")` and
   `pipelines/*.yaml`.
4. Add an end-to-end test that drives it through the API.

## Adding a driver

Implement `DeviceDriver` (`probe`, `get_running_config`, `apply_config`, `restore_config`,
`run_check`), raise `DriverError` for device-side failures, register it in `get_driver()`, and
expose it through `HATCH_DRIVER`. The simulated driver is the reference implementation.

## Commit style

Small, focused commits with imperative subjects (`Add ZTP token expiry`), each passing lint
and tests.

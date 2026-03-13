# NovaOps Memory Snapshot

Last updated: 2026-03-13

## Implemented in this session

1. Jury deliberation parallelization
- File: `Agent_Jury/jury_orchestrator.py`
- Change: replaced sequential juror loop with `ThreadPoolExecutor(max_workers=len(jurors))`.
- Added per-juror timeout handling (`juror_timeout_seconds`, default 20s).
- Added isolated failure handling (timeout/crash -> juror-specific failure verdict).

2. Jury GitHub repo context configurability
- File: `Agent_Jury/jury_orchestrator.py`
- Added `SERVICE_REPO_MAP` env support for service-to-repo mapping.
- Added metadata override support: `metadata.github.owner` + `metadata.github.repo`.
- Fallback default remains owner=`acme`, repo=`<service_name>`.

3. Metadata plumbed from webhook to jury
- Files: `api/server.py`, `agents/main.py`
- `AlertPayload` now supports `metadata` with `Field(default_factory=dict)`.
- `trigger_agent_loop` passes metadata to `agents.main.run(...)`.
- `agents.main.run(...)` forwards metadata to `JuryOrchestrator.run(...)`.

4. Convergence hard-gate in governance
- File: `governance/gate.py`
- Added override in `GovernanceGate.evaluate(...)`:
  - if convergence disagrees (`agree == false`) OR jury escalation reasons are present,
    decision is forced to `REQUIRE_APPROVAL`
    with policy name `convergence_guard_require_approval`.

## Tests added/updated

1. Added: `tests/test_jury_orchestrator_logic.py`
- Validates repo resolution from `SERVICE_REPO_MAP`.
- Validates metadata override precedence.
- Validates timeout isolation behavior for slow juror.

2. Updated: `tests/test_governance_gate_logic.py`
- Added `test_evaluate_forces_approval_when_convergence_disagrees`.

## Documentation updated

1. `README.md`
- Added March 13 update notes.
- Documented webhook metadata override payload.
- Added `SERVICE_REPO_MAP` env var documentation.
- Updated test count to 48.

2. `IMPLEMENTATION_PLAN.md`
- Added March 13 delta section with implemented changes and verification results.

## Sanity checks run

1. Targeted:
- `python -m unittest tests.test_jury_orchestrator_logic tests.test_governance_gate_logic -v`

2. Full:
- `python -m unittest discover -s tests -v`
- Result: `48 tests`, `OK`.

## Additional session state saved

1. Environment bootstrap file
- Added `.env` at project root with required runtime keys and safe local defaults.
- Includes new `SERVICE_REPO_MAP` example entry for `checkout-service`.

2. Runbook commands shared with user
- Web app run (local): `uvicorn api.server:app --host 0.0.0.0 --port 8082 --env-file .env`
- Incident cleanup commands referenced from README:
  - `Remove-Item history.db -Force -ErrorAction SilentlyContinue`
  - `Remove-Item plans -Recurse -Force -ErrorAction SilentlyContinue`
- Test commands referenced from README:
  - `python -m unittest discover -s tests -v`
  - `python -m evaluation --list|--scenario 1|--domain oom|--all`

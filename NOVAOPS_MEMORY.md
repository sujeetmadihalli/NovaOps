# NovaOps Memory Snapshot

Last updated: 2026-03-15

## Implemented on 2026-03-15: Hardening & Bugfixes

1. Optional approval token for Ghost Mode execution
- Files: `api/server.py`, `lambda_handlers/nova_connect_handler.py`, `sonic_call.py`, `.env.example`, `README.md`
- If `NOVAOPS_APPROVAL_TOKEN` is set, `POST /api/incidents/{id}/approve` and `POST /api/incidents/{id}/reject` now require `X-NovaOps-Approval-Token`.
- Voice Lambda and `sonic_call.py` include the token header when configured.
- Lambda now ignores unexpected `callback_url` values to reduce SSRF risk.

2. Dashboard correctness + safety improvements
- Files: `dashboard/app.js`, `dashboard/snapshot.js`
- Dashboard now uses same-origin `/api/...` paths and fixes the PDF download endpoint mismatch.
- PIR rendering now escapes HTML before inserting into the DOM to reduce XSS risk from generated content.
- Snapshot script now targets `http://localhost:8082/dashboard/`.

3. Log endpoint performance
- File: `api/server.py`
- `GET /api/logs` now tails the last lines efficiently instead of reading the entire log file.

4. Kubernetes rollback execution
- File: `tools/k8s_actions.py`
- `rollback_deployment` in non-mock mode now performs a real rollback by patching the Deployment template to the previous ReplicaSet revision.

5. SQLite backend thread-safety
- File: `api/history_db.py`
- Added a connection-level lock and enabled WAL mode when supported to reduce cross-thread contention.

6. Docker/Git hygiene
- Files: `.dockerignore`, `.gitignore`, `docker-compose.yml`
- Docker builds now exclude `dashboard/node_modules/` and include required markdown assets (skills).
- Git now ignores `history.db` and `evaluation/results/` artifacts.
- `docker-compose.yml` no longer loads `.env` by default in LocalStack/mock mode (reduces accidental secret leakage).

7. Slack/voice rejection + interactive approvals
- Files: `api/server.py`, `api/slack_notifier.py`, `governance/audit_log.py`, `governance/gate.py`, `governance/report.py`, `lambda_handlers/nova_connect_handler.py`, `sonic_call.py`, `.env.example`, `README.md`, `tests/test_api_logic.py`, `tests/test_critical_escalation_integration.py`, `tests/test_nova_connect_handler.py`, `tests/test_voice_e2e_manual.py`
- Added `POST /slack/actions` with Slack signature verification via `SLACK_SIGNING_SECRET`.
- Added `POST /api/incidents/{id}/reject` to record human denial (DB status + audit trail + governance.json).
- Voice Lambda and `sonic_call.py` now call `/reject` on `[ACTION_REJECTED]`.
- Audit log event allowlist now includes `CONVERGENCE_CHECK` and `HUMAN_REJECTED`.
- `GovernanceGate.approve_and_execute()` accepts an `actor` so Slack approvals can be attributed in the audit log.

8. Simulation results now show in the dashboard (Docker/LocalStack backend)
- Files: `run_simulations.sh`, `tools/sync_history_sqlite_to_dynamodb.py`
- Root cause: the evaluation harness was writing incidents into local SQLite (`history.db`) while the dashboard API was reading from LocalStack DynamoDB.
- `run_simulations.sh` now auto-detects LocalStack and sets `DYNAMODB_ENDPOINT`/`S3_ENDPOINT` + test creds so simulations write to DynamoDB and appear in `/api/incidents`.
- Added a one-time sync tool to backfill existing SQLite incidents into DynamoDB when needed.

## Implemented on 2026-03-15: Critical Incident Voice Escalation

### New modules

1. **Escalation Policy Engine** (`api/escalation_policy.py`)
   - Classifies incidents as critical vs normal based on severity + risk score.
   - Configurable via `CRITICAL_SEVERITY_LEVELS` (default: `P1`) and `CRITICAL_RISK_SCORE_THRESHOLD` (default: `85`).
   - Master switch: `NOVAOPS_VOICE_ESCALATION_ENABLED`.
   - Auto-executed incidents are automatically skipped.

2. **Voice Summary Builder** (`api/voice_summary.py`)
   - `build_briefing_script()`: generates <=60-word TTS script for Polly playback.
   - `build_system_prompt()`: generates full Nova system prompt for real-time conversation.
   - Includes incident ID, service, severity, domain, analysis excerpt, proposed action, approval/rejection tokens.

3. **Amazon Connect Caller** (`api/connect_caller.py`)
   - Wraps `StartOutboundVoiceContact` API.
   - Passes incident context as Contact Flow attributes.
   - Mock mode logs calls instead of dialing.
   - Returns `CallResult` with success flag, contact_id, or error.

4. **Lambda Handler** (`lambda_handlers/nova_connect_handler.py`)
   - Lex V2 fulfillment Lambda for Connect Contact Flow.
   - Bridges caller speech to Nova via `bedrock.converse()`.
   - Conversation history carried in Lex session attributes (trimmed to 12 messages).
   - Detects `[ACTION_APPROVED]` / `[ACTION_REJECTED]` tokens.
   - On approval: calls back to `POST /api/incidents/{id}/approve`.
   - On rejection: calls back to `POST /api/incidents/{id}/reject`.
   - On Bedrock failure: returns fallback message and closes conversation.

### Modified modules

5. **Slack Notifier** (`api/slack_notifier.py`)
   - Added `send_critical_escalation()` method.
   - High-visibility Block Kit message with severity, call status, escalation reasons.
   - Used as supplement to phone call or fallback when call fails.

6. **Server Integration** (`api/server.py`)
   - Added `_try_voice_escalation()` function hooked into `trigger_agent_loop()`.
   - Called after `db.log_incident()` and `notifier.send_incident_plan()`.
   - Flow: evaluate policy -> build briefing/prompt -> place call -> Slack critical -> save artifact.
   - Added `_save_escalation_artifact()` to persist `voice_escalation.json` in `plans/{incident_id}/`.
   - Imported and initialized `EscalationPolicy` and `ConnectCaller` as module-level singletons.

### Configuration added

7. **Environment variables** (documented in `.env.example`):
   - `NOVAOPS_VOICE_ESCALATION_ENABLED`, `NOVAOPS_VOICE_USE_MOCK`
   - `CRITICAL_SEVERITY_LEVELS`, `CRITICAL_RISK_SCORE_THRESHOLD`
   - `CONNECT_INSTANCE_ID`, `CONNECT_CONTACT_FLOW_ID`, `CONNECT_SOURCE_PHONE`, `ONCALL_PHONE_NUMBER`
   - `NOVAOPS_API_CALLBACK_URL`

### Tests added

8. Test files created:
   - `tests/test_escalation_policy.py` -- 12 unit tests
   - `tests/test_voice_summary.py` -- 19 unit tests
   - `tests/test_connect_caller.py` -- 6 unit tests
   - `tests/test_nova_connect_handler.py` -- 10 unit tests
   - `tests/test_critical_escalation_integration.py` -- 8 integration tests
   - `tests/test_voice_e2e_manual.py` -- 20 comprehensive E2E tests
   - **Total: 124 tests passing** (latest full suite run)

### Documentation updated

9. Files updated:
   - `README.md` -- added voice escalation section, updated pipeline diagram, env vars, artifacts, test count
   - `AGENTS.md` -- updated architecture, directories, artifacts, env vars
   - `AWS_PERMISSIONS_GUIDE.md` -- added Connect/Lex IAM permissions
   - `EVALUATION_GUIDE.md` -- added voice escalation demo phase
   - `project_context.md` -- rewritten to match current architecture
   - `.env.example` -- created with all env vars documented

---

## Implemented on 2026-03-13: Jury Parallelization & Convergence Guard

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

## Sanity checks run

1. Full test suite: `python -m unittest discover -s tests -v` -- 124 tests pass (WSL venv, Python 3.10)

# NovaOps v2

Autonomous multi-agent SRE war room powered by Amazon Nova 2 Lite, with independent jury validation.

NovaOps v2 responds to production alerts end-to-end:
1. Triage the incident.
2. Run specialist investigation agents.
3. Validate with an adversarial critic.
4. Run an independent jury pipeline.
5. Compare both pipelines in a convergence check.
6. Gate remediation through governance policy.

Every major event is written to an append-only audit trail. Human override is always available.

Built for the Amazon Nova AI Hackathon 2026.

---

## March 13, 2026 Updates

- Jury deliberation now runs concurrently with `ThreadPoolExecutor` and per-juror timeout isolation.
- Jury GitHub context is now configurable per service using `SERVICE_REPO_MAP`, with optional alert-level override via webhook `metadata.github`.
- Governance now hard-gates convergence disagreements and jury escalations to `REQUIRE_APPROVAL`, regardless of auto-allow policy matches.

---

## Why This Architecture

NovaOps intentionally uses two independent reasoning paths:
- **War Room:** Deep sequential investigation and action planning.
- **Jury:** Blind validation from raw context only (no War Room reasoning).

This separation reduces groupthink risk and catches confident-but-wrong actions.

| Risk | War Room only | Jury only | Hybrid (NovaOps v2) |
|---|---|---|---|
| Triage misclassifies domain | Can propagate | Mostly immune | Jury catches blind spot |
| Weak root-cause hypothesis | Critic may catch | Limited self-correction | Critic + jury cross-check |
| High confidence but wrong action | Can pass alone | Can pass alone | Must converge or escalate |
| Unknown/external anomaly | Partial signal | Partial signal | Double-validated path |

---

## How It Works

### Stage 1: War Room
- **Triage Agent** classifies domain, severity, and service.
- Four specialists run in parallel:
  - Log Analyst
  - Metrics Analyst
  - K8s Inspector
  - GitHub Analyst
- **Root Cause Reasoner** synthesizes findings.
- **Critic Agent** performs adversarial review (up to 3 loops).
- **Remediation Planner** proposes action (`rollback`, `restart`, `scale`, `noop`).

### Stage 2: Jury Validation (Independent)
- 4 jurors deliberate in parallel on raw incident context only:
  - Log Analyst
  - Infra Specialist
  - Deploy Specialist
  - Anomaly Specialist
- **Judge LLM** synthesizes juror verdicts.
- **Escalation Gate** runs safety checks.

### Stage 3: Convergence + Governance
- Compare War Room action vs Jury action.
- If they agree and no jury escalation: confidence boosted.
- If they disagree or jury escalates: confidence penalized and decision forced to `REQUIRE_APPROVAL`.
- Governance policy outputs `ALLOW_AUTO` or `REQUIRE_APPROVAL`.

All typed outputs are written to `plans/{incident_id}/` for inspection.

---

## Governance Model

### Risk score (0-100)
- Action weight: `rollback=40`, `restart=20`, `scale=15`, `noop=0`
- Severity weight: `P1=30`, `P2=20`, `P3=10`, `P4=5`
- Confidence penalty: `max(0, (0.75 - confidence) * 40)`

### Policy decisions (first match wins)

| Policy | Condition | Decision |
|---|---|---|
| `noop_requires_approval` | action=`noop` | `REQUIRE_APPROVAL` |
| `p1_always_requires_approval` | severity=`P1` | `REQUIRE_APPROVAL` |
| `rollback_always_requires_approval` | action=`rollback` | `REQUIRE_APPROVAL` |
| `low_confidence_escalate` | confidence `< 0.65` | `REQUIRE_APPROVAL` |
| `high_confidence_p3_p4_auto` | `P3/P4` + `restart/scale` + confidence `>= 0.75` | `ALLOW_AUTO` |
| `p2_scale_high_confidence` | `P2` + `scale` + confidence `>= 0.85` | `ALLOW_AUTO` |
| `default_require_approval` | catch-all | `REQUIRE_APPROVAL` |

### Confidence precedence
`convergence.adjusted_confidence > critic.confidence > root_cause.confidence_overall > top_hypothesis.confidence > 0.0`

---

## Quick Start (Mock Mode)

### PowerShell (Windows)
```powershell
cd G:\NovaOps\Music\NovaOps-v2
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:PYTHONPATH = "."
$env:NOVAOPS_USE_MOCK = "1"
python -m agents "P2 OOM alert on payment-service in prod"
```

### Bash
```bash
cd /path/to/NovaOps-v2
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export PYTHONPATH=.
export NOVAOPS_USE_MOCK=1
python -m agents "P2 OOM alert on payment-service in prod"
```

---

## Run Modes

### Docker
```powershell
cd G:\NovaOps\Music\NovaOps-v2
docker compose up --build
```

Run evaluation harness in container:
```powershell
docker compose exec -e PYTHONPATH=. -e NOVAOPS_USE_MOCK=1 novaops-api python evaluation_harness/multi_scenario_test.py
```

### Local Python (Web/API)
```powershell
cd G:\NovaOps\Music\NovaOps-v2
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."
$env:NOVAOPS_USE_MOCK = "1"
uvicorn api.server:app --host 0.0.0.0 --port 8082
```

Dashboard and docs:
- Dashboard: `http://localhost:8082/`
- API docs: `http://localhost:8082/docs`

> On Windows, avoid `--reload` with uvicorn to prevent subprocess/python-path issues.

---

## Live Mode (Amazon Nova 2 Lite on Bedrock)

```bash
export AWS_DEFAULT_REGION=us-east-2
export AWS_BEARER_TOKEN_BEDROCK=<your-token>
export NOVAOPS_USE_MOCK=0
python -m agents "P2 traffic surge on checkout-service in prod"
```

---

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/webhook/pagerduty` | Trigger full 3-stage investigation |
| `GET` | `/api/incidents/{id}` | Fetch status and artifacts |
| `POST` | `/api/incidents/{id}/approve` | Human approval path through governance |
| `GET` | `/api/governance/{id}/decision` | Fetch governance decision |
| `GET` | `/api/governance/{id}/audit` | Fetch governance audit details |

Sample webhook payload (with optional jury GitHub context):

```json
{
  "alert_name": "P2 latency alert",
  "service_name": "checkout-service",
  "namespace": "prod",
  "description": "traffic surge in checkout",
  "metadata": {
    "github": {
      "owner": "acme-inc",
      "repo": "checkout-api"
    }
  }
}
```

---

## Storage Backends

| Environment | Backend | Selection |
|---|---|---|
| Local uvicorn | SQLite (`history.db`) | `DYNAMODB_ENDPOINT` not set |
| Docker + LocalStack | DynamoDB | `DYNAMODB_ENDPOINT=http://localstack:4566` |

`api/history_db.py` uses `get_incident_db()` to auto-select the backend.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NOVAOPS_USE_MOCK` | `true` | Offline mode (no Bedrock calls) |
| `NOVA_MODEL_ID` | `us.amazon.nova-2-lite-v1:0` | Bedrock inference profile |
| `AWS_DEFAULT_REGION` | `us-east-1` | Bedrock/LocalStack region |
| `AWS_BEARER_TOKEN_BEDROCK` | - | Bedrock bearer token |
| `HACKATHON_MODE` | `false` | Alias for mock mode |
| `SLACK_WEBHOOK_URL` | - | Ghost Mode approval notifications |
| `USE_BEDROCK_KB` | `false` | Enable managed Bedrock KB for RAG |
| `DYNAMODB_ENDPOINT` | - | LocalStack endpoint for DynamoDB backend |
| `S3_ENDPOINT` | - | LocalStack endpoint for PIR PDF URLs |
| `NOVAOPS_LOG_PATH` | `novaops.log` | Unified log file path |
| `HISTORY_DB_PATH` | `history.db` | Override SQLite file path |
| `SERVICE_REPO_MAP` | - | JSON map for jury GitHub context |

`SERVICE_REPO_MAP` example:
```json
{
  "checkout-service": {
    "owner": "acme-inc",
    "repo": "checkout-api"
  }
}
```

---

## Repository Layout

```text
agents/           War Room orchestration graph, prompts, schemas, artifacts
Agent_Jury/       Jury pipeline (4 jurors + Judge + Escalation Gate)
agent/            Bedrock client used by jury jurors
pipeline/         Convergence check (War Room vs Jury)
aggregator/       Logs, metrics, Kubernetes, GitHub fetchers (live + mock)
api/              FastAPI server, history DB backends, Slack notifier, webhook
governance/       GovernanceGate, PolicyEngine, AuditLog, report generator
tools/            Tool wrappers, RemediationExecutor, retrieval
evaluation/       Multi-scenario evaluation harness
skills/           Domain playbooks (oom, traffic_surge, deadlock, etc.)
runbooks/         Learned PIR content for RAG
plans/            Generated investigation artifacts (git-ignored)
tests/            Unit tests
```

---

## Evaluation and Tests

```bash
python -m evaluation --list
python -m evaluation --scenario 1
python -m evaluation --domain oom
python -m evaluation --all
```

```bash
python -m unittest discover -s tests -v
```

---

## Investigation Artifacts

Each incident writes to `plans/{incident_id}/`:

| File | Contents |
|---|---|
| `report.md` | Full investigation report |
| `governance.json` | Policy decision, risk, confidence, convergence source |
| `governance_report.md` | Human-readable governance summary |
| `audit.jsonl` | Append-only event log |
| `structured.json` | Typed agent outputs |
| `validation.json` | Schema validation scores |
| `trace.json` | Failure metadata (if investigation fails) |
| `findings/*.json` | Per-agent structured findings |
| `plan.md` | Investigation plan, finalized to `COMPLETED` |

---

## Clear Old Incidents

### Local (SQLite)
```powershell
Remove-Item history.db -Force -ErrorAction SilentlyContinue
Remove-Item plans -Recurse -Force -ErrorAction SilentlyContinue
```

### Docker (DynamoDB via LocalStack)
```powershell
docker compose down -v
docker compose up --build
```

---

## Notes

- For Docker-specific troubleshooting and fix history, see `docker_fixes.md`.
- To populate demo incidents while API is running, execute `python trigger_test_incidents.py` in a separate terminal.

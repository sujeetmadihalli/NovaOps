# NovaOps v2

**Autonomous multi-agent SRE war room powered by Amazon Nova 2 Lite — with independent jury validation.**

NovaOps v2 responds to production alerts end-to-end: it triages the incident, dispatches four specialist analysts in parallel, reasons over their findings, validates the reasoning path with an adversarial critic, then runs a completely independent jury validation before gating the action through a policy engine. Every decision is logged to an append-only audit trail. Human override is always available.

Built for Enterprise scale incident management using Amazon Nova foundational models.

---

## Latest Release Features

- **Amazon Nova Sonic Integration**: Live, real-time simulated voice calls via AWS Bedrock for human-in-the-loop action approval.
- **Unified Telemetry Dashboard**: Complete, colorized logging of all War Room, Jury, and API operations piped directly into a single `novaops_system.log` stream.
- **Streamlined Evaluation Engine**: A refined 4-script demonstration framework executing automated system orchestration, mock scenario injection, and live failure testing.
- Jury deliberation now executes concurrently via `ThreadPoolExecutor` with per-juror timeout isolation.
- Jury GitHub context is now configurable by service using `SERVICE_REPO_MAP` and can be overridden per alert using webhook `metadata.github`.
- Governance now hard-gates convergence disagreements and jury escalations to `REQUIRE_APPROVAL` regardless of policy auto-allow.

---

## How It Works

The pipeline has three stages. The War Room and the Jury run independently — the Jury never sees the War Room's reasoning. Their conclusions are compared in the Convergence Check before the Governance Gate makes the final call.

```
Alert (POST /webhook/pagerduty)
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  STAGE 1: WAR ROOM  (deep sequential investigation)      │
│                                                          │
│  Triage Agent          classifies domain, severity, svc  │
│    │                                                     │
│    ├── Log Analyst ────────────────────────┐             │
│    ├── Metrics Analyst ────────────────────┤ parallel    │
│    ├── K8s Inspector ──────────────────────┤             │
│    └── GitHub Analyst ─────────────────────┘             │
│    │                                                     │
│  Root Cause Reasoner   synthesises findings              │
│    │                                                     │
│  Critic Agent          adversarial review, loop x3 max   │
│    │                                                     │
│  Remediation Planner   proposes rollback/scale/restart   │
└────────────────────────────┬─────────────────────────────┘
                             │ proposed_action + domain
                             │
                             │ raw context only (no war room reasoning)
                             ▼
┌──────────────────────────────────────────────────────────┐
│  STAGE 2: JURY VALIDATION  (independent blind panel)     │
│                                                          │
│  4 specialist jurors deliberate in parallel              │
│  on raw incident context — no war room influence         │
│                                                          │
│  ┌────────────────┐  ┌──────────────────────────────┐   │
│  │ Log Analyst    │  │ Infra Specialist              │   │
│  │ logs, OOM,     │  │ K8s pod health, CPU/mem       │   │
│  │ crash traces   │  │ OOMKilled, scaling signals    │   │
│  └────────────────┘  └──────────────────────────────┘   │
│  ┌────────────────┐  ┌──────────────────────────────┐   │
│  │ Deploy         │  │ Anomaly Specialist            │   │
│  │ Specialist     │  │ Layer 1: RAG signal           │   │
│  │ git commits,   │  │ Layer 2: regex pattern scan   │   │
│  │ config regs    │  │ Layer 3: LLM residual         │   │
│  └────────────────┘  └──────────────────────────────┘   │
│                │                                         │
│             Judge LLM — synthesises 4 verdicts           │
│             Escalation Gate — 6 safety checks            │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│  STAGE 3: CONVERGENCE CHECK                              │
│                                                          │
│  War Room action == Jury action?                         │
│                                                          │
│  AGREE  + no jury escalation                            │
│    → confidence boosted (+0.15)                          │
│    → GovernanceGate may ALLOW_AUTO                       │
│                                                          │
│  DISAGREE or jury escalation                             │
│    → confidence penalised (-0.30)                        │
│    → GovernanceGate forces REQUIRE_APPROVAL              │
│    → Slack shows both perspectives with full reasoning   │
└────────────────────────────┬─────────────────────────────┘
                             │ adjusted_confidence
                             ▼
┌──────────────────────────────────────────────────────────┐
│  GOVERNANCE GATE                                         │
│  Risk score + policy → ALLOW_AUTO | REQUIRE_APPROVAL     │
│  Audit trail updated with CONVERGENCE_CHECK event        │
└──────────────────────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│  EXECUTION & APPROVAL                                    │
│                                                          │
│  ALLOW_AUTO ───────► Auto-Remediate (K8s API)            │
│  REQUIRE_APPROVAL ─► Amazon Nova Sonic Phone Call        │
│                      (Real-time Voice/Text Fallback)     │
└──────────────────────────────────────────────────────────┘
```

All agent outputs are validated against typed schemas and written to `plans/{incident_id}/` as inspectable JSON artifacts.

---

## Why Two Pipelines?

The War Room and Jury solve different failure modes:

| Risk | War Room alone | Jury alone | Hybrid |
|---|---|---|---|
| Triage misclassifies domain | Propagates to all agents | Immune | Jury catches blind spot |
| Weak hypothesis | Critic may catch it | No self-correction | Critic + independent jury |
| Confident but wrong | Passes gate | Passes gate | Both must agree |
| Unknown / external incident | Anomaly specialist | Anomaly specialist | Double-validated |

The **key design principle**: jurors receive only the raw incident context — not the War Room's reasoning. This preserves full independence and prevents groupthink.

---

## Governance

Every proposed remediation passes through a policy engine before execution.

**Risk score (0-100):**
- Action weight: rollback=40, restart=20, scale=15, noop=0
- Severity weight: P1=30, P2=20, P3=10, P4=5
- Confidence penalty: `max(0, (0.75 - confidence) * 40)` for low-confidence decisions

When the Convergence Check runs, the adjusted confidence replaces the raw war room confidence in the risk calculation. In addition, `GovernanceGate` applies a hard guard: disagreement or jury escalation always resolves to `REQUIRE_APPROVAL`.

**Policy decisions (first match wins):**

| Policy | Condition | Decision |
|---|---|---|
| noop_requires_approval | action=noop | REQUIRE_APPROVAL |
| p1_always_requires_approval | severity=P1 | REQUIRE_APPROVAL |
| rollback_always_requires_approval | action=rollback | REQUIRE_APPROVAL |
| low_confidence_escalate | confidence < 0.65 | REQUIRE_APPROVAL |
| high_confidence_p3_p4_auto | P3/P4 + restart/scale + conf >= 0.75 | ALLOW_AUTO |
| p2_scale_high_confidence | P2 + scale + conf >= 0.85 | ALLOW_AUTO |
| default_require_approval | (catch-all) | REQUIRE_APPROVAL |

**Confidence precedence:**
`convergence.adjusted_confidence > critic.confidence > root_cause.confidence_overall > top_hypothesis.confidence > 0.0`

**Artifacts written per incident:**
- `governance.json` — full decision record
- `governance_report.md` — human-readable summary with risk bar and audit table
- `audit.jsonl` — append-only event log including `CONVERGENCE_CHECK` event

---

## Audit Trail Events

Every incident generates a complete, ordered audit trail in `plans/{incident_id}/audit.jsonl`:

| Event | Actor | When |
|---|---|---|
| `ALERT_RECEIVED` | SYSTEM | Webhook received |
| `TRIAGE_COMPLETE` | SYSTEM | Domain, severity, service classified |
| `HYPOTHESIS_FORMED` | SYSTEM | Root cause ranked |
| `CRITIC_VERDICT` | SYSTEM | Adversarial review completed |
| `CONVERGENCE_CHECK` | SYSTEM | War Room vs Jury compared |
| `GOVERNANCE_DECISION` | SYSTEM | Policy evaluated, risk scored |
| `EXECUTION_STARTED` | SYSTEM/HUMAN | Tool execution begins |
| `EXECUTION_COMPLETE` | SYSTEM/HUMAN | Tool execution result |
| `HUMAN_OVERRIDE` | HUMAN | Manual approval via `/approve` |

---

## Repository Layout

```
agents/         War Room orchestration graph, prompts, schemas, artifacts, PIR generation
Agent_Jury/     Jury pipeline — 4 specialist jurors + Judge + Escalation Gate
  jurors/       Log Analyst, Infra Specialist, Deployment Specialist, Anomaly Specialist
agent/          nova_client.py — Bedrock client used by Jury jurors
pipeline/       convergence.py — War Room vs Jury agreement check
aggregator/     Log, metric, Kubernetes, and GitHub data fetchers (live + mock)
api/            FastAPI server, dual-backend history DB (SQLite local / DynamoDB Docker), Slack notifier, PagerDuty webhook
governance/     GovernanceGate, PolicyEngine, AuditLog, report generator
tools/          Tool wrappers, RemediationExecutor, knowledge retrieval
evaluation/     15 scenario harness covering 6 failure domains
skills/         Domain playbooks (oom, traffic_surge, deadlock, config_drift, ...)
runbooks/       Learned PIR content for RAG
plans/          Generated investigation artifacts (git-ignored)
tests/          37 unit tests
```

---

## Quick Start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run in fully offline mock mode (no Bedrock spend)
NOVAOPS_USE_MOCK=1 python -m agents "P2 OOM alert on payment-service in prod"
```

## Evaluation & Demonstration

To seamlessly evaluate the entire Amazon Nova Auto-SRE ecosystem from start to finish, you only need to execute four simple scripts in order:

### 1. Start the System
Brings the entire backend API, LocalStack, and K8s Minikube online. All logs are piped into one master log file.
```bash
./start_system.sh
```
*Wait ~15 seconds for the Docker containers to spin up. You can view progress using `tail -f novaops_system.log`.*

### 2. Run 7 Simulated Incidents (Mocked)
Fires 7 deterministic, test-case incidents into the AWS Bedrock pipeline. This populates your dashboard with rich War Room and Jury investigation records to evaluate system performance.
```bash
./run_simulated_incidents.sh
```
*Open `http://localhost:8081` to view their deep analysis.*

### 3. Run a Live System Failure (Minikube + Nova Sonic)
Forces an Out-Of-Memory (OOM) leak on a live Kubernetes service. The NovaOps Agent will detect it, investigate it, draft a remediation, and execute a **real-time simulated phone call** to ask you for verbal approval using the Amazon Nova 2 Sonic model!
```bash
./run_live_k8s_test.sh
```

### 4. Stop Everything
Cleanly destroys the Docker network, shuts off Minikube, kills background loggers, and leaves your system tidy.
```bash
./stop_system.sh
```

- Dashboard: `http://localhost:8082/`
- API docs (Swagger): `http://localhost:8082/docs` (served via `/novaops.json`)

### AWS & System Permissions

If you are setting this project up on a new machine or AWS account for evaluation, please refer to the [AWS Permissions Guide](AWS_PERMISSIONS_GUIDE.md) before executing the scripts. **Amazon Bedrock Foundation Model Access must be explicitly granted in the AWS console.**

### API endpoints

```
POST /webhook/pagerduty           — trigger full 3-stage investigation
GET  /api/incidents/{id}          — fetch status + artifacts
POST /api/incidents/{id}/approve  — human approval → governance gate → execution
GET  /api/governance/{id}/decision
GET  /api/governance/{id}/audit
```

`POST /webhook/pagerduty` supports optional metadata for jury repo context:

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

NovaOps v2 uses a dual-backend design for incident history:

| Environment | Backend | How selected |
|---|---|---|
| Local uvicorn | SQLite (`history.db`) | `DYNAMODB_ENDPOINT` not set |
| Docker / LocalStack | DynamoDB via LocalStack | `DYNAMODB_ENDPOINT=http://localstack:4566` |

The factory function `get_incident_db()` in `api/history_db.py` automatically selects the correct backend based on the `DYNAMODB_ENDPOINT` environment variable. Both backends expose an identical interface (`log_incident`, `get_incident`, `update_status`, `save_pir`, `get_recent_incidents`).

In Docker, LocalStack initialises the DynamoDB table on first use (lazy init — no startup blocking). The S3 bucket `novaops-pir-reports` is created by `init-aws.sh` which LocalStack runs automatically when ready.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NOVAOPS_USE_MOCK` | `true` | Offline mode — no Bedrock calls, controls War Room and Jury |
| `NOVA_MODEL_ID` | `us.amazon.nova-2-lite-v1:0` | Bedrock inference profile |
| `AWS_DEFAULT_REGION` | `us-east-1` | Bedrock / LocalStack region |
| `AWS_BEARER_TOKEN_BEDROCK` | — | Bearer token for Bedrock access |
| `LOCAL_EVAL_MODE` | `false` | Alias for mock mode |
| `SLACK_WEBHOOK_URL` | — | Ghost Mode approval notifications |
| `USE_BEDROCK_KB` | `false` | Use managed Bedrock Knowledge Bases for RAG |
| `DYNAMODB_ENDPOINT` | — | Set to LocalStack URL in Docker; selects DynamoDB backend |
| `S3_ENDPOINT` | — | Set to LocalStack URL in Docker; used for PIR PDF presigned URLs |
| `NOVAOPS_LOG_PATH` | `novaops.log` | Path to the unified log file read by the dashboard live terminal |
| `HISTORY_DB_PATH` | `history.db` | Override SQLite file path (local only) |
| `SERVICE_REPO_MAP` | — | JSON map for jury GitHub context. Example: `{"checkout-service":{"owner":"acme-inc","repo":"checkout-api"}}` |

---

## Evaluation

```bash
python -m evaluation --list          # show all 15 scenarios
python -m evaluation --scenario 1    # run one scenario
python -m evaluation --domain oom    # run all OOM scenarios
python -m evaluation --all           # run full suite
```

Scenarios cover: `oom`, `traffic_surge`, `deadlock`, `config_drift`, `dependency_failure`, `cascading_failure`.

---

## Tests

```bash
python -m unittest discover -s tests -v
# 48 tests
```

---

## Artifacts

Each investigation writes to `plans/{incident_id}/`:

| File | Contents |
|---|---|
| `report.md` | Full investigation report |
| `governance.json` | Policy decision, risk score, confidence, convergence source |
| `governance_report.md` | Human-readable governance summary |
| `audit.jsonl` | Append-only event log including CONVERGENCE_CHECK |
| `structured.json` | Typed agent outputs |
| `validation.json` | Schema validation scores |
| `trace.json` | Failure metadata (if investigation failed) |
| `findings/*.json` | Per-agent structured findings |
| `plan.md` | Investigation plan (updated to COMPLETED) |

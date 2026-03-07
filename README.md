# NovaOps: Autonomous Production Incident Resolution Agent

**NovaOps** is an autonomous, event-driven agent that transitions production incidents from "alerting" directly to "resolving." Built around the **300K context window of Amazon Nova Pro**, it ingests sprawling diagnostic data — logs, metrics, Kubernetes events, git histories — reasons about root causes using Chain-of-Thought prompting, and proposes safe, constrained remediations in seconds.

> **Human MTTR:** ~15-20 minutes (wake up, VPN, triage across 5 dashboards)
> **NovaOps MTTR:** ~10-15 seconds (parallel aggregation + LLM reasoning + Slack dispatch)

---

## Key Features

| Feature | Description |
|---|---|
| **ReAct Reasoning Engine** | Chain-of-Thought prompting with a 3-attempt self-correction retry loop. Regex-based JSON extraction strips `<thinking>` tags for clean tool invocations. |
| **ReAct Feedback Loop** | `query_more_logs` is a live intermediate step, not a dead end. When the agent requests more context, the orchestrator fetches extended CloudWatch logs and re-invokes the LLM with enriched context until a final remediation is committed. |
| **Jury Agent System** | A second, independent LLM pipeline routes complex incidents through 4 specialist jurors (Log Analyst, Infra Specialist, Deployment Specialist, Anomaly Specialist) whose verdicts are synthesised by a Judge LLM into a binding final decision. |
| **Escalation Gate** | A 6-check safety layer between the jury verdict and any action. Low confidence, juror disagreement, unknown incident categories, and external outages all route to human review — nothing is silently dropped. |
| **Anomaly Specialist (3-Layer Detection)** | The fourth juror detects external API failures, DNS outages, database connection errors, and security breaches using RAG signal, regex pattern scanning, and LLM residual analysis. |
| **TF-IDF Knowledge Base** | Zero-dependency runbook search. Indexes markdown runbooks and scores them against incoming alerts for contextual RAG injection. |
| **Self-Learning Runbooks** | When a Post-Incident Report is generated, it is automatically saved as a new `.md` runbook (if no similar one exists), growing the knowledge base over time. Service-scoped deduplication ensures the same alert on different services gets separate runbooks. |
| **Post-Incident Reports (PIR)** | One-click PIR generation via Amazon Nova. Reports are rendered as formatted HTML in the dashboard modal and exported as styled PDFs. |
| **Ghost Mode (Human-in-the-Loop)** | The agent never executes autonomously in production. It posts its hypothesis and an "Approve" button to Slack, requiring human approval before any action is taken. |
| **Dead Man's Snitch** | If the agent or jury crashes, or the Nova API is unreachable, a critical Slack alert fires immediately to page human SREs. Every failure path routes to a human — nothing is silently swallowed. |
| **Live Telemetry Logs** | Dashboard tab streaming the unified `novaops.log` buffer with ANSI color-coded service prefixes. |
| **Execution Sandbox** | Tools are strictly typed, whitelisted, and safety-capped (e.g., max 20 replicas on `scale_deployment`). |
| **7/7 Evaluation Harness** | 7 diverse incident scenarios testing the agent's reasoning — OOM, traffic surge, deadlock, bad config, cache bloat, third-party outage, and zero-shot (no runbook). |

---

## System Architecture

NovaOps exposes two independent incident pipelines on the same FastAPI gateway. Both share the same context aggregators but run completely separate reasoning chains.

```
PagerDuty / OpsGenie Alert
           │
           ▼
┌──────────────────────────────────────────────────────┐
│                 EVENT GATEWAY (FastAPI)              │
│                    api/server.py :8000               │
│                                                      │
│    POST /webhook/pagerduty    POST /webhook/jury     │
└───────────┬──────────────────────────┬───────────────┘
            │  Background Task         │  Background Task
            ▼                          ▼
   ┌─────────────────┐       ┌──────────────────────┐
   │  MAIN AGENT     │       │   JURY AGENT         │
   │  orchestrator   │       │   jury_orchestrator  │
   └────────┬────────┘       └──────────┬───────────┘
            │                           │
            └──────────┬────────────────┘
                       ▼
        ┌──────────────────────────────────────┐
        │       CONTEXT AGGREGATORS            │
        │  ┌──────────┐  ┌──────────┐         │
        │  │CloudWatch│  │Prometheus│         │
        │  │  Logs    │  │ Metrics  │         │
        │  └──────────┘  └──────────┘         │
        │  ┌──────────┐  ┌──────────┐         │
        │  │   K8s    │  │  GitHub  │         │
        │  │  Events  │  │ Commits  │         │
        │  └──────────┘  └──────────┘         │
        └──────────────────────────────────────┘
                       │
                       ▼
        ┌──────────────────────────────────────┐
        │      TF-IDF KNOWLEDGE BASE (RAG)     │
        │   runbooks/*.md → Score → Inject     │
        └──────────────┬───────────────────────┘
                       │
           ┌───────────┴────────────┐
           │                        │
           ▼                        ▼
  ┌─────────────────┐    ┌──────────────────────┐
  │  MAIN AGENT     │    │  JURY PIPELINE       │
  │  REASONING      │    │  (see below)         │
  │  LOOP           │    └──────────────────────┘
  │                 │
  │  Attempt 1..3   │
  │  ┌───────────┐  │
  │  │ Nova Pro  │  │
  │  │ CoT JSON  │  │
  │  └─────┬─────┘  │
  │        │        │
  │  query_more_    │
  │  logs? ├──Yes──►│ Fetch extended logs
  │        │        │ Inject → re-reason
  │        │No      │
  │        ▼        │
  │  Validate tool  │
  │  (sandbox)      │
  └────────┬────────┘
           │
           ▼
  ┌──────────────────────────────────┐
  │         GHOST MODE               │
  │  Slack: "Approve Exec Plan?"     │
  │  Human approves → tool executes  │
  └──────────────────────────────────┘
           │
           ▼
  ┌──────────────────────────────────┐
  │       SELF-LEARNING LOOP         │
  │  PIR Generated → auto-save .md   │
  │  runbook (novel incidents only)  │
  │  → Re-index TF-IDF corpus        │
  └──────────────────────────────────┘
```

---

## Jury Agent System

The Jury Agent is a second, fully independent LLM pipeline designed for complex incidents that benefit from multiple expert perspectives. It is triggered via `/webhook/jury` and never touches the main orchestrator's error handlers.

### Pipeline Flow

```
Incident Alert  →  /webhook/jury
                        │
                        ▼
            ┌───────────────────────┐
            │  1. OBSERVE           │
            │  Same aggregators as  │
            │  main agent: Logs,    │
            │  Metrics, K8s, Git,   │
            │  RAG runbook          │
            └───────────┬───────────┘
                        │
                        ▼
            ┌───────────────────────────────────────────────────┐
            │  2. DELIBERATE  (parallel specialist analysis)    │
            │                                                   │
            │  ┌─────────────────┐  ┌───────────────────────┐  │
            │  │ Log Analyst     │  │ Infra Specialist      │  │
            │  │ Error patterns  │  │ CPU/Mem, OOMKilled,   │  │
            │  │ crash traces    │  │ K8s pod health        │  │
            │  │ OOM, exceptions │  │ scaling signals       │  │
            │  │ conf: 0.0–1.0   │  │ conf: 0.0–1.0         │  │
            │  └────────┬────────┘  └──────────┬────────────┘  │
            │           │                       │               │
            │  ┌────────┴──────┐  ┌─────────────┴───────────┐  │
            │  │ Deployment    │  │ Anomaly Specialist      │  │
            │  │ Specialist    │  │ Layer 1: RAG signal     │  │
            │  │ Commit timing │  │ Layer 2: Regex patterns │  │
            │  │ config regs   │  │  (DNS, DB, Ext-API,     │  │
            │  │ runbook match │  │   Security)             │  │
            │  │ conf: 0.0–1.0 │  │ Layer 3: LLM residual  │  │
            │  └────────┬──────┘  └─────────────┬───────────┘  │
            └───────────┼─────────────────────────┼─────────────┘
                        │   4 verdicts            │
                        └──────────┬──────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │  3. JUDGE                │
                    │  Synthesises all 4       │
                    │  juror verdicts          │
                    │  Resolves disagreements  │
                    │  Weighs confidence       │
                    │  → final_root_cause      │
                    │  → proposed_action       │
                    │  → confidence score      │
                    └──────────────┬───────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │  4. ESCALATION GATE      │
                    │  6 safety checks:        │
                    │  [ ] Pipeline failure    │
                    │  [ ] Judge conf < 0.6    │
                    │  [ ] Juror conf = 0.0    │
                    │  [ ] Juror disagreement  │
                    │  [ ] Anomaly categories  │
                    │  [ ] noop_require_human  │
                    └──────┬───────────────────┘
                           │
              ┌────────────┴──────────────┐
              │ Any flag triggered?        │
              │                           │
              ▼ YES                       ▼ NO
   ┌──────────────────┐       ┌────────────────────────┐
   │ ESCALATE         │       │ STANDARD APPROVAL      │
   │ Human Review via │       │ Send verdict to Slack  │
   │ Slack with full  │       │ for human sign-off     │
   │ jury summary     │       │ before execution       │
   └──────────────────┘       └────────────────────────┘
```

### Anomaly Specialist Detection Layers

The fourth juror uses three stacked detection layers to surface incident categories that the other three jurors cannot diagnose:

| Layer | Method | Covers |
|---|---|---|
| **Layer 1 — RAG Signal** | Low TF-IDF runbook score → no known pattern | Novel / first-seen errors |
| **Layer 2 — Pattern Scan** | Regex across logs and K8s events | External API failures, DNS resolution errors, DB connection refused, security/auth anomalies |
| **Layer 3 — LLM Residual** | Amazon Nova analyses remaining unexplained signals | Unknown or compound root causes |

If pattern scan finds hits but the LLM is uncertain (confidence < 0.5), the specialist boosts confidence to 0.6 and attaches `detected_categories` to the verdict. The Escalation Gate uses these categories to trigger human review.

---

## ReAct Feedback Loop

The main agent treats `query_more_logs` as a live intermediate reasoning step rather than a final answer:

```
LLM chooses query_more_logs
          │
          ▼
Orchestrator fetches extended CloudWatch logs
(using minutes_back from LLM's own parameters)
          │
          ▼
Injects extended logs into context:
"--- EXTENDED LOGS (60 min) ---
 ... enriched history ...
 Commit to a final remediation. Do NOT query again."
          │
          ▼
LLM re-reasons with full history → picks real action
(rollback / scale / restart / noop_require_human)
          │
          ▼
Returns plan_ready with remediation action
```

If `query_more_logs` is picked again after enrichment (or any other loop exhausts `MAX_RETRIES=3`), the orchestrator returns `status: failed` → Dead Man's Snitch fires → human is paged immediately.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/webhook/pagerduty` | Triggers the main single-agent ReAct pipeline |
| `POST` | `/webhook/jury` | Triggers the 4-juror + Judge jury pipeline |
| `GET` | `/api/incidents` | Returns last 50 incidents from the history DB |
| `GET` | `/api/logs` | Returns last 500 filtered lines from `novaops.log` |
| `POST` | `/api/incidents/{id}/report` | Generates a PIR for the incident via Nova |
| `GET` | `/api/incidents/{id}/report` | Returns an existing PIR |
| `GET` | `/health` | Health check |

---

## Quick Start

### Prerequisites

- Python 3.10+ with a virtual environment
- **AWS Account** with Bedrock access to `amazon.nova-pro-v1:0`
- Minikube + kubectl (optional, for live K8s telemetry — falls back to mock)

### 1. Configure AWS Credentials

Create a `.env` file in the project root:

```env
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/your/webhook/url
```

### 2. Install Dependencies

```powershell
& "E:\VirtualEnvs\apiapp-YRc1n0Op\Scripts\Activate.ps1"
cd "e:\Nova Hackathon\NovaOps"
pip install -r requirements.txt
```

### 3. Start the API Backend

Open Terminal 1:

```powershell
& "E:\VirtualEnvs\apiapp-YRc1n0Op\Scripts\Activate.ps1"
cd "e:\Nova Hackathon\NovaOps"
$env:PYTHONPATH = "."
uvicorn api.server:app --reload --port 8000
```

### 4. Start the Dashboard

Open Terminal 2:

```powershell
python -m http.server 8081 --directory dashboard
```

| URL | Purpose |
|---|---|
| `http://localhost:8081` | Dashboard UI |
| `http://localhost:8000/docs` | FastAPI Swagger Docs |
| `http://localhost:8000/health` | Health Check |

### 5. Run the Evaluation Harness

Open Terminal 3:

```powershell
& "E:\VirtualEnvs\apiapp-YRc1n0Op\Scripts\Activate.ps1"
cd "e:\Nova Hackathon\NovaOps"
$env:PYTHONPATH = "."
python evaluation_harness/multi_scenario_test.py
```

Watch the dashboard populate in real-time as the agent resolves each incident.

### 6. Trigger the Jury Pipeline

Send a single incident to the jury endpoint:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/webhook/jury" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"alert_name":"HighMemoryUsage","service_name":"payment-service","namespace":"prod","incident_id":"INC-JURY-001","description":"Memory spike detected"}'
```

### 7. Generate Post-Incident Reports

1. Open `http://localhost:8081`
2. Click **"Post-Incident Report"** on any incident card
3. Amazon Nova generates a structured PIR displayed in a formatted modal
4. Click **"Copy Report"** or find the PDF in `runbooks/pir_reports/`

---

## Evaluation Results (7/7)

The agent achieves **100% accuracy** across 7 diverse incident scenarios, each requiring distinct reasoning:

| # | Scenario | Expected Tool | Why It's Hard |
|---|---|---|---|
| 1 | Bad Deployment OOM | `rollback_deployment` | Recent commit exists → must rollback, not restart |
| 2 | Traffic Surge | `scale_deployment` | High CPU, no bad commit → scaling is the answer |
| 3 | Thread Deadlock | `restart_pods` | 0% CPU but unresponsive → scaling would just create more deadlocked pods |
| 4 | Bad DB Config | `rollback_deployment` | CrashLoop + recent DB config change → rollback the config |
| 5 | Organic Cache Bloat | `restart_pods` | Same OOM as #1, but NO recent commit — rollback makes no sense |
| 6 | Third-Party API Down | `noop_require_human` | Nothing to fix internally — must hand off to humans |
| 7 | Zero-Shot (No Runbook) | `scale_deployment` | Agent has zero instructions, must reason from pre-training alone |

---

## Project Structure

```text
NovaOps/
│
├── .env                              # AWS credentials (user-created)
├── requirements.txt                  # Python dependencies
├── start_novaops.sh                  # Unified launch script (single command)
│
├── api/                              # FastAPI Endpoints & Webhooks
│   ├── server.py                     # Dual-pipeline webhook receiver, PIR endpoints, log streaming
│   ├── slack_notifier.py             # Ghost Mode: Slack approval payloads
│   └── history_db.py                 # SQLite incident history with PIR storage
│
├── agent/                            # Main Single-Agent Pipeline
│   ├── orchestrator.py               # ReAct loop: Observe → Reason → Act → Feedback
│   ├── nova_client.py                # AWS Bedrock client for Amazon Nova Pro
│   ├── knowledge_base.py             # TF-IDF runbook search + self-learning auto-save
│   ├── pir_generator.py              # Post-Incident Report generation via Nova
│   └── pdf_generator.py              # ReportLab PDF export for PIRs
│
├── Agent_Jury/                       # Jury Agent Pipeline (independent system)
│   ├── jury_orchestrator.py          # Entry point: OBSERVE → DELIBERATE → JUDGE → GATE
│   ├── judge.py                      # Judge LLM: synthesises juror verdicts into final ruling
│   ├── escalation_gate.py            # 6-check safety gate: routes uncertain verdicts to humans
│   └── jurors/
│       ├── base_juror.py             # Base class: LLM invocation, JSON parsing, mock routing
│       ├── log_analyst.py            # Juror 1: error logs, crash traces, OOM, exceptions
│       ├── infra_specialist.py       # Juror 2: K8s pod health, CPU/memory, scaling signals
│       ├── deployment_specialist.py  # Juror 3: git commits, deployment timing, config regressions
│       └── anomaly_specialist.py     # Juror 4: external APIs, DNS, DB, security (3-layer detection)
│
├── aggregator/                       # Shared Context Extraction (used by both pipelines)
│   ├── logs.py                       # AWS CloudWatch error/fatal log fetcher
│   ├── metrics.py                    # Prometheus CPU/Memory saturation queries
│   ├── kubernetes_state.py           # K8s pod events (OOMKill, CrashLoop)
│   └── github_history.py             # GitHub commit history fetcher
│
├── tools/                            # Safe Execution Sandbox
│   ├── k8s_actions.py                # Constrained K8s operations (rollback, scale, restart)
│   └── registry.py                   # Maps Nova's JSON tool calls to Python functions
│
├── runbooks/                         # Knowledge Base (TF-IDF indexed)
│   ├── dummy-service-oom.md          # Manual: memory leak → restart_pods
│   ├── redis-oom-error.md            # Manual: Redis OOM → rollback_deployment
│   ├── pir-*.md                      # Auto-generated: self-learned from resolved incidents
│   └── pir_reports/                  # PDF exports of Post-Incident Reports
│
├── dashboard/                        # Glassmorphic Web Dashboard
│   ├── index.html                    # Tabbed UI: Incidents + Live Logs + PIR Modal
│   ├── app.js                        # Fetch, render, ANSI parsing, markdown rendering
│   └── style.css                     # Dark-mode glass design system
│
├── dummy-service/                    # Intentionally Vulnerable Microservice
│   ├── main.py                       # FastAPI app with /memory-leak endpoint
│   ├── k8s.yaml                      # K8s Deployment (500Mi memory limit)
│   └── Dockerfile                    # Container build
│
└── evaluation_harness/
    └── multi_scenario_test.py        # 7-scenario edge case evaluation suite
```

---

## Production AWS Architecture

In a production AWS environment, the local components would be replaced with managed services:

| Local Component | AWS Production Equivalent |
|---|---|
| SQLite (`history.db`) | **Amazon DynamoDB** |
| TF-IDF Knowledge Base | **Amazon Bedrock Knowledge Bases + OpenSearch Serverless** |
| Local Prometheus | **Amazon Managed Prometheus** |
| Dashboard (static HTML) | **Amazon QuickSight** or **Managed Grafana** |
| `novaops.log` file | **Amazon CloudWatch Logs** |
| PIR PDF files | **Amazon S3** |
| Slack Webhooks | **Amazon SNS → Slack / Email / PagerDuty** |

---

*Built with Amazon Nova Pro on AWS Bedrock*

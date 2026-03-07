# NovaOps: Autonomous Production Incident Resolution Agent

**NovaOps** is an autonomous, event-driven agent that transitions production incidents from "alerting" directly to "resolving." Built around the **300K context window of Amazon Nova Pro**, it ingests sprawling diagnostic data — logs, metrics, Kubernetes events, git histories — reasons about root causes using Chain-of-Thought prompting, and proposes safe, constrained remediations in seconds.

> **Human MTTR:** ~15-20 minutes (wake up, VPN, triage across 5 dashboards)
> **NovaOps MTTR:** ~10-15 seconds (parallel aggregation + LLM reasoning + Slack dispatch)

---

## Key Features

| Feature | Description |
|---|---|
| **ReAct Reasoning Engine** | Chain-of-Thought prompting with 3-attempt self-correction retry loop. Regex-based JSON extraction strips `<thinking>` tags for clean tool invocations. |
| **TF-IDF Knowledge Base** | Zero-dependency runbook search. Indexes markdown runbooks and scores them against incoming alerts for contextual RAG injection. |
| **Self-Learning Runbooks** | When a Post-Incident Report is generated, it's automatically saved as a new `.md` runbook (if no similar one exists), growing the knowledge base over time. Service-scoped deduplication ensures the same alert on different services gets separate runbooks. |
| **Post-Incident Reports (PIR)** | One-click PIR generation via Amazon Nova. Reports are rendered as formatted HTML in the dashboard modal and exported as styled PDFs. |
| **Ghost Mode (Human-in-the-Loop)** | The agent never executes autonomously in production. It posts its hypothesis and an "Approve" button to Slack, requiring human approval before any action. |
| **Dead Man's Snitch** | If the agent crashes or the Nova API is unreachable, a critical Slack alert is fired immediately to page human SREs. |
| **Live Telemetry Logs** | Dashboard tab streaming the unified `novaops.log` buffer with ANSI color-coded service prefixes. |
| **Execution Sandbox** | Tools are strictly typed, whitelisted, and safety-capped (e.g., max 20 replicas on `scale_deployment`). |
| **7/7 Evaluation Harness** | 7 diverse incident scenarios testing the agent's reasoning — OOM, traffic surge, deadlock, bad config, cache bloat, third-party outage, and zero-shot (no runbook). |

---

## System Architecture

The architecture is strictly separated into **Read (Observation)** and **Write (Execution)** boundaries for safety.

```
PagerDuty/OpsGenie Alert
        │
        ▼
┌─────────────────────────────────────────────────┐
│              EVENT GATEWAY (FastAPI)             │
│              api/server.py :8000                 │
└────────────────────┬────────────────────────────┘
                     │  Background Task
                     ▼
┌─────────────────────────────────────────────────┐
│           CONTEXT AGGREGATORS (parallel)         │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────┐ │
│  │CloudWatch│ │Prometheus│ │  K8s   │ │GitHub│ │
│  │  Logs    │ │ Metrics  │ │ Events │ │Commits│ │
│  └──────────┘ └──────────┘ └────────┘ └──────┘ │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│          TF-IDF KNOWLEDGE BASE (RAG)            │
│   runbooks/*.md → Tokenize → Score → Inject     │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│     AMAZON NOVA PRO REASONING ENGINE            │
│  Chain-of-Thought → JSON Tool Call → Validate   │
│  3-attempt self-correction retry loop           │
└────────┬───────────────────────────┬────────────┘
         │                           │
         ▼                           ▼
┌─────────────────┐     ┌──────────────────────┐
│ EXECUTION       │     │  GHOST MODE          │
│ SANDBOX         │     │  Slack Approval      │
│ tools/          │     │  "Approve Exec Plan" │
└─────────────────┘     └──────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│           SELF-LEARNING LOOP                    │
│  PIR Generated → Auto-save as .md runbook       │
│  (if novel alert+service combo)                 │
│  → Re-index TF-IDF corpus immediately           │
└─────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- **Minikube** and **kubectl** installed (for live K8s telemetry)
- **Helm** installed (for Prometheus monitoring stack)
- **Python 3.10+** with `venv`
- **AWS Account** with Bedrock access to `amazon.nova-pro-v1:0`

### 1. Configure AWS Credentials

Create a `.env` file in the project root:

```env
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/your/webhook/url
```

### 2. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Launch Everything (Single Command)

Make sure Minikube is running (`minikube start`) with the dummy service and Prometheus stack deployed.

```bash
chmod +x start_novaops.sh
./start_novaops.sh
```

This single script:
- Kills any orphaned processes on ports 8000, 8080, 8081, 9090
- Starts Kubernetes port-forwards for Prometheus and the dummy service
- Boots the FastAPI Event Gateway on port 8000
- Boots the Dashboard UI on port 8081
- Streams all output with color-coded prefixes to a unified terminal

| URL | Purpose |
|---|---|
| `http://localhost:8081` | Dashboard UI |
| `http://localhost:8000/docs` | FastAPI Swagger Docs |
| `http://localhost:8000/health` | Health Check |

### 4. Run the Evaluation Harness

In a **new terminal**, trigger all 7 test scenarios:

```bash
PYTHONPATH=. venv/bin/python evaluation_harness/multi_scenario_test.py
```

Watch the Dashboard populate in real-time as the agent resolves each incident.

### 5. Generate Post-Incident Reports

1. Open the dashboard at `http://localhost:8081`
2. Click **"Post-Incident Report"** on any incident card
3. Amazon Nova generates a structured PIR displayed in a formatted modal
4. Click **"Copy Report"** to clipboard, or find the PDF in `runbooks/pir_reports/`

### 6. View Live Telemetry Logs

Click the **"Live Telemetry Logs"** tab in the dashboard to see the real-time NovaOps log stream with color-coded service prefixes:
- `[Nova-Agent]` — LLM reasoning and tool decisions
- `[Event-API]` — FastAPI server activity
- `[K8s-Prom]` — Kubernetes port-forward status
- `[Dashboard]` — UI server activity

---

## Evaluation Results (7/7)

The agent achieves **100% accuracy** across 7 diverse incident scenarios, each requiring different reasoning:

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
incident-agent/
│
├── .env                              # AWS credentials (user-created)
├── requirements.txt                  # Python dependencies
├── start_novaops.sh                  # Unified launch script (single command)
├── start_demo.sh                     # Legacy K8s port-forward script
│
├── api/                              # FastAPI Endpoints & Webhooks
│   ├── server.py                     # Webhook receiver, PIR endpoints, log streaming
│   ├── slack_notifier.py             # Ghost Mode: Slack approval payloads
│   └── history_db.py                 # SQLite incident history with PIR storage
│
├── agent/                            # The AI Brain
│   ├── orchestrator.py               # ReAct loop: Observe → Reason → Act
│   ├── nova_client.py                # AWS Bedrock client for Amazon Nova Pro
│   ├── knowledge_base.py             # TF-IDF runbook search + self-learning auto-save
│   ├── pir_generator.py              # Post-Incident Report generation via Nova
│   └── pdf_generator.py              # ReportLab PDF export for PIRs
│
├── aggregator/                       # Context Extraction Pipeline
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
| Slack Webhooks | **Amazon SNS → Slack/Email/PagerDuty** |

---

*Built with Amazon Nova Pro on AWS Bedrock*

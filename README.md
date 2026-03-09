# NovaOps: Autonomous Incident Resolution Agent

NovaOps is an event-driven incident response system that collects runtime context (logs, metrics, Kubernetes events, commit history, runbooks), asks Amazon Nova Pro for a remediation plan, and sends that plan to humans for approval.

## Current System Version

- Version line: `AWS + LocalStack simulation profile`
- Active branch: `aws-localstack-sim`
- Last updated: `March 9, 2026`
- Runtime mode: `FastAPI + Docker + LocalStack + Minikube + dashboard`

## What Is Running Today

- Event API: FastAPI (`api/server.py`) in Docker, exposed at `http://localhost:8082`
- Data persistence: DynamoDB table (`IncidentHistory`) on LocalStack (`:4566`)
- PIR PDF storage: S3 bucket (`novaops-pir-reports`) on LocalStack
- Dashboard: static `http.server` on `http://localhost:8081`
- Telemetry sources:
  - CloudWatch logs (falls back to mock if access denied)
  - Prometheus (`http://localhost:9090` via port-forward)
  - Kubernetes events (from Minikube)
  - GitHub commits (token-based, mock fallback)

## Core Features

- ReAct-style incident reasoning loop with JSON tool selection
- Tool sandbox for constrained actions (`rollback_deployment`, `scale_deployment`, `restart_pods`, `noop_require_human`)
- TF-IDF runbook retrieval (`runbooks/*.md`)
- PIR generation with Amazon Nova + PDF export
- Ghost mode notifications to Slack (human-in-the-loop approval)
- Live log stream in dashboard (`/api/logs`)

## System Architecture

The architecture is separated into read/observe and write/act boundaries for safety.

```text
                        Host (WSL / Linux)
  +--------------------+                +------------------------+
  | Dashboard UI       |  HTTP :8081    | Alert Source           |
  | (python http.server)+--------------> | PagerDuty/OpsGenie    |
  +---------+----------+                +-----------+------------+
            |                                        |
            | GET /api/*                             | POST /webhook/pagerduty
            v                                        v
  +---------------------------------------------------------------+
  | Event Gateway API (FastAPI in Docker)                         |
  | container :8000  -> host :8082                                |
  | api/server.py                                                 |
  +-------------------+--------------------------+----------------+
                      |                          |
                      | read/write history       | generate PIR PDF / download URL
                      v                          v
         +------------------------+      +------------------------+
         | LocalStack DynamoDB    |      | LocalStack S3          |
         | IncidentHistory table  |      | novaops-pir-reports    |
         +------------------------+      +------------------------+
                      ^
                      |
                      | background incident loop
                      v
  +---------------------------------------------------------------+
  | Agent Orchestrator (ReAct)                                    |
  | Context aggregators: CloudWatch, Prometheus(:9090), K8s, GitHub|
  | + TF-IDF RAG (runbooks/*.md) + Nova Pro reasoning             |
  +----------------------+-------------------------------+---------+
                         |                               |
                         | action proposal               | handoff
                         v                               v
               +---------------------+        +----------------------+
               | Tool Sandbox        |        | Ghost Mode (Slack)   |
               | rollback/scale/restart|      | Approve Exec Plan    |
               +---------------------+        +----------------------+
                         |
                         v
                +-------------------------------+
                | Self-learning loop            |
                | PIR -> runbook save -> reindex|
                +-------------------------------+
```

## Quick Start (WSL Recommended)

### 1. Prerequisites

- WSL2 (Ubuntu 22.04 recommended)
- Docker Desktop (WSL integration enabled)
- Minikube
- kubectl
- Helm (for Prometheus stack if needed)
- AWS credentials with Bedrock model access (`amazon.nova-pro-v1:0`)

### 2. Configure `.env`

Create `incident-agent/.env`:

```env
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/your/webhook/url
```

### 3. Start the full stack

```bash
cd /mnt/d/Projects/AmazonNova/incident-agent
chmod +x start_novaops.sh
./start_novaops.sh
```

This script:

- validates/starts Minikube
- starts `kubectl port-forward` for:
  - Prometheus `9090:9090`
  - dummy-service `8080:8080`
- runs `docker compose up -d --build` (LocalStack + API)
- starts dashboard on port `8081`
- streams logs to `novaops.log`

### 4. Verify health

- Dashboard: `http://localhost:8081`
- API health: `http://localhost:8082/health`
- API docs: `http://localhost:8082/docs`

## Running Tests

```bash
cd /mnt/d/Projects/AmazonNova/incident-agent
source venv/bin/activate
python -m pytest -q
```

## Evaluation Harness

Run multi-scenario validation:

```bash
cd /mnt/d/Projects/AmazonNova/incident-agent
source venv/bin/activate
PYTHONPATH=. python evaluation_harness/multi_scenario_test.py
```

## Incident Simulation

Use the all-in-one script:

```bash
cd /mnt/d/Projects/AmazonNova/incident-agent
chmod +x simulate_incident.sh
./simulate_incident.sh
```

Current behavior:

- tries `minikube service dummy-service --url` with timeout
- falls back to `http://localhost:8080` if URL resolution blocks
- triggers `/memory-leak`
- posts alert to `POST http://localhost:8082/webhook/pagerduty`

## API Endpoints (Current)

- `GET /health`
- `GET /api/incidents`
- `GET /api/logs`
- `POST /webhook/pagerduty`
- `POST /api/incidents/{incident_id}/report`
- `GET /api/incidents/{incident_id}/report`
- `GET /api/download-pdf?key=<s3_object_key>`

## Project Structure

```text
incident-agent/
├── agent/                # Orchestrator, Nova client, PIR/RAG logic
├── aggregator/           # Logs, metrics, k8s, github context collectors
├── api/                  # FastAPI server, notifier, DynamoDB layer
├── dashboard/            # Frontend UI (incidents, logs, PIR modal)
├── dummy-service/        # Test workload to simulate failures
├── evaluation_harness/   # Scenario-based evaluation scripts
├── runbooks/             # Manual + auto-learned runbooks and PIR reports
├── tools/                # Action sandbox registry + k8s actions
├── docker-compose.yml    # LocalStack + API runtime
├── start_novaops.sh      # Main startup script
└── simulate_incident.sh  # End-to-end incident simulation script
```

## Notes

- The system is demo-safe: remediation is proposed and notified, not automatically executed in production.
- Several integrations intentionally degrade gracefully to mock data when external dependencies are unavailable.

---

Built with Amazon Nova Pro on AWS Bedrock.



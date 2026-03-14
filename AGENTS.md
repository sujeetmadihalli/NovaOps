# NovaOps v2 - AGENTS.md

> Repository map for agents working in this codebase.

## What This Project Is

NovaOps v2 is a multi-agent SRE war room for production incident response.
It investigates alerts using specialist agents, builds hypotheses with evidence,
routes through a critic gate, proposes safe remediation, and records artifacts
for review.

## Architecture

```text
Alert/Webhook
    |
    v
Triage Agent
    |
    v
Log Analyst | Metrics Analyst | K8s Inspector | GitHub Analyst
    |
    v
Root Cause Reasoner
    |
    v
Critic
    |
    +--> fail -> reflection loop back to analysts
    |
    +--> pass -> Remediation Planner
                    |
                    v
                Ghost Mode approval
                    |
                    v
             Execute + verify + report
```

## Key Directories

| Path | Purpose |
|------|---------|
| `agents/` | Agent orchestration, prompts, schemas, artifacts, PIR generation |
| `aggregator/` | Data fetchers for logs, metrics, Kubernetes, GitHub |
| `tools/` | Investigation tools, remediation executor, knowledge retrieval |
| `api/` | FastAPI server, SQLite history, Slack notifier |
| `evaluation/` | Scenario runner and mock incident cases |
| `skills/` | Shared and domain-specific playbooks |
| `plans/` | Runtime investigation artifacts |
| `runbooks/` | Learned PIR/runbook content |
| `scripts/` | Optional helper scripts such as managed KB setup |
| `tests/` | Unit tests for parsing, artifacts, execution, API flow |
| `claude code/` | Project status, working plan, and session log |

## Runtime Artifacts

Each investigation writes into `plans/{incident_id}/`:

- `plan.md`
- `report.md`
- `hypotheses.md`
- `reasoning.md`
- `structured.json`
- `validation.json`
- `trace.json`
- `findings/*.json`
- `findings/loop_01.md`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AWS_DEFAULT_REGION` | Yes | AWS region, default `us-east-1` |
| `AWS_ACCESS_KEY_ID` | For live AWS calls | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | For live AWS calls | AWS credentials |
| `NOVA_MODEL_ID` | No | Bedrock model ID override |
| `NOVAOPS_USE_MOCK` | No | Use mock aggregators and mock execution |
| `HACKATHON_MODE` | No | Force low-cost local retrieval path |
| `SLACK_WEBHOOK_URL` | No | Slack incoming webhook |
| `KNOWLEDGE_BASE_ID` | No | Managed Bedrock KB identifier |
| `LOG_LEVEL` | No | Logging verbosity |

## Working Rules

- Keep the Ghost Mode approval boundary intact.
- Prefer local retrieval and low-cost paths for hackathon use.
- Treat schema validation as a first-class part of the pipeline.
- Keep `claude code/STATUS.md`, `PLAN.md`, and `SESSION.md` aligned with reality.

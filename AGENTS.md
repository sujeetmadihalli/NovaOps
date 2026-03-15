# NovaOps v2 - AGENTS.md

> Repository map for agents working in this codebase.

## What This Project Is

NovaOps v2 is a multi-agent SRE war room for production incident response.
It investigates alerts using specialist agents, builds hypotheses with evidence,
validates through an independent blind jury, routes through a governance gate,
and escalates critical incidents via outbound phone calls powered by
Amazon Connect + Nova real-time conversation.

## Architecture

```text
Alert/Webhook (POST /webhook/pagerduty)
    |
    v
Triage Agent (classifies domain, severity, service)
    |
    v
Log Analyst | Metrics Analyst | K8s Inspector | GitHub Analyst  (parallel)
    |
    v
Root Cause Reasoner (synthesises findings)
    |
    v
Critic Agent (adversarial review, max 3 loops)
    |
    +--> fail -> reflection loop back to analysts
    |
    +--> pass -> Remediation Planner
                    |
                    v
              Jury Validation (4 independent jurors, parallel)
                    |
                    v
              Convergence Check (War Room vs Jury agreement)
                    |
                    v
              Governance Gate (risk score + policy)
                    |
                    +---> ALLOW_AUTO -> Execute immediately
                    |
                    +---> REQUIRE_APPROVAL -> Escalation Policy
                              |
                              +---> CRITICAL (P1 / high risk)
                              |       -> Amazon Connect outbound call
                              |       -> Nova real-time voice conversation
                              |       -> Verbal approval triggers execution
                              |       -> Slack critical escalation (supplement/fallback)
                              |
                              +---> NORMAL
                                      -> Slack Ghost Mode notification
                                      -> Await manual /approve
```

## Key Directories

| Path | Purpose |
|------|---------|
| `agents/` | War Room orchestration graph, prompts, schemas, artifacts, PIR generation |
| `Agent_Jury/` | Jury pipeline -- 4 specialist jurors + Judge + Escalation Gate |
| `agent/` | nova_client.py -- Bedrock client used by Jury jurors |
| `pipeline/` | convergence.py -- War Room vs Jury agreement check |
| `aggregator/` | Data fetchers for logs, metrics, Kubernetes, GitHub (live + mock) |
| `api/` | FastAPI server, history DB, Slack notifier, escalation policy, voice summary, Connect caller |
| `lambda_handlers/` | Lambda function for Lex V2 fulfillment -- bridges phone audio to Nova real-time |
| `governance/` | GovernanceGate, PolicyEngine, AuditLog, report generator |
| `tools/` | Tool wrappers, RemediationExecutor, knowledge retrieval |
| `evaluation/` | 15-scenario harness covering 6 failure domains |
| `skills/` | Shared and domain-specific playbooks (oom, traffic_surge, deadlock, config_drift, ...) |
| `plans/` | Runtime investigation artifacts (git-ignored) |
| `runbooks/` | Learned PIR/runbook content for RAG |
| `dashboard/` | Vue.js frontend UI |
| `tests/` | 104 unit + integration tests |

## Runtime Artifacts

Each investigation writes into `plans/{incident_id}/`:

- `plan.md` -- Investigation plan (updated to COMPLETED)
- `report.md` -- Full investigation report
- `governance.json` -- Policy decision, risk score, confidence, convergence source
- `governance_report.md` -- Human-readable governance summary
- `audit.jsonl` -- Append-only event log
- `structured.json` -- Typed agent outputs
- `validation.json` -- Schema validation scores
- `trace.json` -- Failure metadata (if investigation failed)
- `findings/*.json` -- Per-agent structured findings
- `voice_escalation.json` -- Voice escalation metadata (critical incidents only)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AWS_DEFAULT_REGION` | Yes | AWS region, default `us-east-1` |
| `AWS_ACCESS_KEY_ID` | For live AWS calls | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | For live AWS calls | AWS credentials |
| `NOVA_MODEL_ID` | No | Bedrock model ID override (default: `us.amazon.nova-2-lite-v1:0`) |
| `NOVAOPS_USE_MOCK` | No | Use mock aggregators and mock execution (default: `true`) |
| `LOCAL_EVAL_MODE` | No | Force low-cost local retrieval path |
| `SLACK_WEBHOOK_URL` | No | Slack incoming webhook for Ghost Mode notifications |
| `SERVICE_REPO_MAP` | No | JSON map for jury GitHub context |
| `NOVAOPS_LOG_PATH` | No | Path to unified log file (default: `novaops.log`) |
| `HISTORY_DB_PATH` | No | Override SQLite file path (default: `history.db`) |
| `DYNAMODB_ENDPOINT` | No | LocalStack DynamoDB URL (Docker only) |
| `S3_ENDPOINT` | No | LocalStack S3 URL (Docker only) |
| **Voice Escalation** | | |
| `NOVAOPS_VOICE_ESCALATION_ENABLED` | No | Master switch (default: `true`) |
| `NOVAOPS_VOICE_USE_MOCK` | No | Mock mode -- logs instead of calling (default: `true`) |
| `CRITICAL_SEVERITY_LEVELS` | No | Severities that trigger voice escalation (default: `P1`) |
| `CRITICAL_RISK_SCORE_THRESHOLD` | No | Risk score threshold (default: `85`) |
| `CONNECT_INSTANCE_ID` | For real calls | Amazon Connect instance ID |
| `CONNECT_CONTACT_FLOW_ID` | For real calls | Contact Flow for voice escalation |
| `CONNECT_SOURCE_PHONE` | For real calls | Outbound caller ID (E.164) |
| `ONCALL_PHONE_NUMBER` | For real calls | On-call engineer's phone (E.164) |
| `NOVAOPS_API_CALLBACK_URL` | No | URL Lambda uses for approval callback (default: `http://localhost:8082`) |

## Working Rules

- Keep the Ghost Mode approval boundary intact.
- Voice escalation informs humans -- it never auto-approves.
- Prefer local retrieval and low-cost paths for evaluation use.
- Treat schema validation as a first-class part of the pipeline.
- All remediation flows through GovernanceGate with full audit trail.

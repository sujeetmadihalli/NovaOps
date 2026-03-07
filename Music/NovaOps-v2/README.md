# NovaOps v2

NovaOps v2 is a multi-agent incident response system built for the Amazon Nova hackathon track. It investigates alerts with specialist agents, validates the reasoning path, proposes safe remediation, and stores a full filesystem-first audit trail for demo and review.

## Current State

- Multi-agent graph orchestration with triage, analysts, reasoner, critic, and remediation planner
- Full governance gate with policy decisions, risk scoring, and append-only audit logs
- Typed schema validation for agent outputs
- Ghost Mode approval before remediation execution
- Offline mock mode for demo-safe runs without Bedrock access
- Local knowledge retrieval by default for hackathon-safe cost control
- Investigation artifacts written to `plans/{incident_id}/`
- Evaluation harness with scenario-based scoring
- Test suite covering parsing, execution, artifacts, API flow, retrieval mode, governance, and offline runtime behavior

## Repository Layout

- `agents/`: orchestration, prompts, schemas, artifacts, PIR generation
- `aggregator/`: log, metric, Kubernetes, and GitHub data fetchers
- `tools/`: tool wrappers, executor, knowledge retrieval
- `api/`: FastAPI server, history database, Slack notifier
- `evaluation/`: scenarios and runner
- `skills/`: shared and domain-specific playbooks
- `plans/`: generated investigation outputs
- `runbooks/`: learned PIR content
- `tests/`: unit tests

## Quick Start

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
$env:NOVAOPS_USE_MOCK="1"
venv\Scripts\python.exe -m agents.main "P2 traffic surge alert on checkout-service in prod causing elevated latency"
```

## Hackathon Defaults

The project is set up to avoid unnecessary managed-service spend:

- `HACKATHON_MODE=true`
- `NOVAOPS_USE_MOCK=true` means fully offline incident investigation and mock execution
- local TF-IDF knowledge retrieval is preferred unless you explicitly opt into managed Bedrock KB usage

The managed setup helper in `scripts/setup_bedrock_kb.py` requires `--allow-managed-kb`.

## Runtime Modes

- Mock mode:
  - Set `NOVAOPS_USE_MOCK=true`
  - No live Bedrock calls are made for investigation or remediation
  - Deterministic offline agent outputs are generated for demo and testing
- Live mode:
  - Set `NOVAOPS_USE_MOCK=false`
  - Requires Bedrock access and the normal AWS environment variables
  - Falls back safely to human escalation if runtime execution fails

## Governance

NovaOps v2 now evaluates every proposed action through a governance layer:

- policy-driven decision: `ALLOW_AUTO`, `REQUIRE_APPROVAL`, or `DENY`
- risk scoring based on action, severity, and confidence
- append-only audit trail in `plans/{incident_id}/audit.jsonl`
- persisted governance decision in `plans/{incident_id}/governance.json`
- human-readable governance summary in `plans/{incident_id}/governance_report.md`

## Run Tests

```powershell
venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Main Artifacts

Each run creates a folder under `plans/` containing:

- `report.md`
- `governance.json`
- `governance_report.md`
- `audit.jsonl`
- `structured.json`
- `validation.json`
- `trace.json`
- `findings/*.json`

These files are intended to be demoable and inspectable without needing a debugger.

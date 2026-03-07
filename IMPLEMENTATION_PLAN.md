# Autonomous Production Incident Resolution Agent

## Goal Description

Build an autonomous, event-driven agent capable of ingesting high-volume context (logs, metrics, deployment history) during a production incident, reasoning about the root cause utilizing Amazon Nova's 300K context window, and safely executing targeted remediation steps.

To ensure extremely high accuracy and safe production deployment, the architecture prioritises a "Ghost Mode" (human-in-the-loop) strategy, robust historical evaluation, and a highly constrained tool sandbox.

---

## System Architecture

The overarching architecture is event-driven and strictly separated into read (observation) and write (action) boundaries. The system exposes two independent incident pipelines — the **Main Agent** and the **Jury Agent** — behind the same Event Gateway.

```
Monitoring / Alerting
PagerDuty, Datadog
        │
        │ Webhook
        ▼
┌───────────────────────────────────────┐
│         Event Gateway (FastAPI)       │
│              api/server.py            │
│                                       │
│  POST /webhook/pagerduty              │
│  POST /webhook/jury                   │
└───────┬───────────────────────┬───────┘
        │ Incident Meta         │ Incident Meta
        ▼                       ▼
┌───────────────────────────────────────┐
│         Context Aggregator            │
│  (shared by both pipelines)           │
│                                       │
│  Logs          Metrics                │
│  OpenSearch/   Prometheus/            │
│  CloudWatch    Datadog                │
│                                       │
│  K8s State     GitHub API             │
│  pod events,   recent commits,        │
│  OOMKills      merged PRs             │
└───────┬───────────────────────┬───────┘
        │ Massive Context       │ Query Alert Runbook
        │ Payload               ▼
        │               ┌──────────────────┐
        │               │  Knowledge Base  │
        │               │  TF-IDF / RAG    │
        │               │  runbooks/*.md   │
        │               └────────┬─────────┘
        │                        │ Relevant Runbook
        └──────────┬─────────────┘
                   │
       ┌───────────┴──────────────┐
       │                          │
       ▼                          ▼
┌──────────────┐        ┌──────────────────────┐
│  MAIN AGENT  │        │     JURY AGENT        │
│  (ReAct)     │        │  (4 Jurors + Judge)   │
└──────┬───────┘        └──────────┬────────────┘
       │                           │
       │ 1. Propose                │ 1. Deliberate
       │    Remediation Plan       │    (parallel)
       ▼                           ▼
┌─────────────────────────────────────────────┐
│              Ghost Mode                     │
│         Human-in-the-Loop (Slack)           │
│     "Engineer clicks Approve"               │
└─────────────────────┬───────────────────────┘
                      │ 2. Engineer Approves
                      ▼
              ┌───────────────┐
              │ Action        │
              │ Execution     │
              │ (K8s API)     │
              └───────┬───────┘
                      │ Result Output
                      ▼
              ┌───────────────┐
              │  Postmortem   │
              │  Generator    │
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │ Slack         │
              │ Notification  │
              └───────────────┘
```

---

## Component Descriptions

### 1. Event Gateway (Trigger)

A FastAPI application that acts as the webhook receiver for alerting systems (PagerDuty, OpsGenie, Datadog Monitors). It extracts the incident metadata and initialises an agent run via a background task so the webhook returns immediately.

Two endpoints:
- `POST /webhook/pagerduty` — routes to the Main Agent ReAct pipeline
- `POST /webhook/jury` — routes to the Jury Agent pipeline

### 2. Context Aggregator (Read-Only Data Fetchers)

Once triggered, this module parallelises the fetching of state from the ecosystem to build the massive context payload:

- **Logs**: Queries OpenSearch / Elasticsearch / AWS CloudWatch for `ERROR` / `FATAL` logs filtered by time and affected service.
- **Metrics**: Pulls CPU, Memory, and Network saturation data via Prometheus / Datadog APIs.
- **State**: Uses Kubernetes API to fetch recent pod events (`kubectl get events`), crash loop statuses, and OOM kills.
- **Change History**: Uses GitHub/GitLab API to retrieve commits and PRs merged to the affected service in the last 24 hours.

Both pipelines share the same aggregator instances.

### 3. Knowledge Base (RAG)

A TF-IDF indexed corpus of Markdown runbooks and auto-generated Post-Incident Reports (PIRs). Runbooks are scored against the incoming alert name and the highest-scoring match is injected as contextual "tribal knowledge" into the LLM prompt.

**Self-learning**: When a PIR is generated after a resolved incident, it is automatically saved as a new `.md` runbook if no similar entry exists for that alert+service combination. The TF-IDF corpus is re-indexed immediately so future incidents benefit.

### 4. Reasoning Engine — Main Agent (ReAct Loop)

The core orchestration logic running in `agent/orchestrator.py`, powered by **Amazon Nova Pro**. It runs a ReAct (Reasoning and Acting) loop:

- Ingests the 300K token aggregated context.
- Formulates a root cause hypothesis inside `<thinking>` tags.
- Outputs a strictly typed JSON tool call.
- Validates the tool against a whitelist (sandbox).
- **ReAct Feedback Loop**: If the agent requests `query_more_logs`, the orchestrator executes the tool immediately — fetching extended CloudWatch logs using the agent's own `minutes_back` parameter — injects the results back into context, and re-invokes Nova to commit to a final remediation. The agent cannot call `query_more_logs` twice; on the second pass it must choose a real action.
- Retries up to 3 times with self-correction prompts for malformed JSON or invalid tool selections.
- On exhausting retries, returns `status: failed` → Dead Man's Snitch fires → human is paged.

### 5. Reasoning Engine — Jury Agent (Multi-LLM Pipeline)

An independent, second reasoning pipeline in `Agent_Jury/`, designed for incidents that benefit from multiple expert perspectives. It never touches the main orchestrator's error handlers.

**Pipeline phases:**

**Phase 1 — OBSERVE**: Uses the same aggregators and RAG as the main agent to build the full incident context.

**Phase 2 — DELIBERATE**: Four specialist LLM jurors analyse the context independently in parallel:

| Juror | Specialisation |
|---|---|
| Log Analyst | Error patterns, crash traces, OOM exceptions, stack traces |
| Infra Specialist | K8s pod health, CPU/memory saturation, OOMKilled, scaling signals |
| Deployment Specialist | Git commit timing, config regressions, runbook match confidence |
| Anomaly Specialist | External APIs, DNS failures, DB connection errors, security anomalies (3-layer detection) |

Each juror returns a verdict: `{verdict, recommended_action, confidence, reasoning}`.

**Anomaly Specialist — 3-Layer Detection:**

| Layer | Method | Covers |
|---|---|---|
| Layer 1 — RAG Signal | Low TF-IDF score → no known runbook pattern | Novel / first-seen errors |
| Layer 2 — Pattern Scan | Regex across logs and K8s events | External APIs, DNS, DB connection refused, security/auth anomalies |
| Layer 3 — LLM Residual | Nova analyses remaining unexplained signals | Unknown or compound root causes |

**Phase 3 — JUDGE**: A Judge LLM receives all four verdicts, weighs confidence scores, resolves disagreements, and produces: `{final_root_cause, judge_reasoning, proposed_action, confidence, dissenting_jurors}`.

**Phase 4 — ESCALATION GATE**: Six safety checks are evaluated before any action proceeds:

| Check | Condition | Result |
|---|---|---|
| Pipeline failure | Agent or aggregator crashed | Escalate |
| Low judge confidence | Judge confidence < 0.6 | Escalate |
| Failed juror | Any juror confidence = 0.0 | Escalate |
| Juror disagreement | High-confidence jurors disagree on action | Escalate |
| Anomaly categories detected | Anomaly specialist found external/DNS/DB/security hits | Escalate |
| Noop selected | Judge proposes `noop_require_human` | Escalate |

If any check fires, a full jury summary is posted to Slack for human review. If all pass, the verdict proceeds to Ghost Mode approval.

### 6. Execution Sandbox (Safety Boundary)

To guarantee safety in production, the agent does **NOT** have shell access. It interacts with a strictly typed Tool Registry.

- Every tool is a Python function with hardcoded constraints.
- Kubernetes actions run using a scoped ServiceAccount that is mathematically prevented from performing destructive actions (e.g., it can `rollout undo` or `scale`, but cannot `delete deployment` or touch databases).
- Maximum replica cap on `scale_deployment`: 20.

Available tools:

| Tool | Description |
|---|---|
| `rollback_deployment` | Rolls back the last deployment for a given service |
| `scale_deployment` | Increases replica count up to a hardcoded cap |
| `restart_pods` | Performs a rolling restart to clear deadlocks or cache |
| `query_more_logs` | Fetches extended log history (ReAct intermediate step, not a final answer) |
| `noop_require_human` | Hands off to a human SRE with full context |

### 7. Human-in-the-Loop & Notifier ("Ghost Mode")

A Slack integration that serves as the agent's voice. When either pipeline arrives at a remediation plan, it posts a summary of the root cause and presents an **"Execute Plan"** button. A human engineer clicks to approve the action.

**Dead Man's Snitch**: Every failure path (pipeline crash, max retries exceeded, low jury confidence, unknown incident type) routes to a critical Slack alert. Nothing is silently dropped.

Once accuracy is proven over time, Ghost Mode can be bypassed for specific low-risk, high-confidence alert types.

---

## Module Structure

```text
NovaOps/
│
├── api/
│   ├── server.py              # Dual-pipeline webhook receiver; /webhook/pagerduty + /webhook/jury
│   ├── slack_notifier.py      # Ghost Mode Slack payloads and Dead Man's Snitch
│   └── history_db.py          # SQLite incident history with PIR storage
│
├── agent/                     # Main Single-Agent Pipeline
│   ├── orchestrator.py        # ReAct loop with query_more_logs feedback execution
│   ├── nova_client.py         # AWS Bedrock client for Amazon Nova Pro
│   ├── knowledge_base.py      # TF-IDF runbook search + self-learning auto-save
│   ├── pir_generator.py       # Post-Incident Report generation via Nova
│   └── pdf_generator.py       # ReportLab PDF export for PIRs
│
├── Agent_Jury/                # Jury Agent Pipeline (independent of main orchestrator)
│   ├── jury_orchestrator.py   # Entry point: OBSERVE → DELIBERATE → JUDGE → GATE
│   ├── judge.py               # Judge LLM: synthesises 4 verdicts into a binding ruling
│   ├── escalation_gate.py     # 6-check safety gate: routes uncertain verdicts to humans
│   └── jurors/
│       ├── base_juror.py      # Base class: LLM invocation, JSON parsing, confidence clamping
│       ├── log_analyst.py     # Juror 1: error logs, crash traces, OOM, exceptions
│       ├── infra_specialist.py       # Juror 2: K8s health, CPU/memory, scaling signals
│       ├── deployment_specialist.py  # Juror 3: git commits, deployment timing, config regressions
│       └── anomaly_specialist.py     # Juror 4: external APIs, DNS, DB, security (3-layer)
│
├── aggregator/                # Shared Context Extraction (used by both pipelines)
│   ├── logs.py                # AWS CloudWatch error/fatal log fetcher
│   ├── metrics.py             # Prometheus CPU/Memory saturation queries
│   ├── kubernetes_state.py    # K8s pod events (OOMKill, CrashLoop)
│   └── github_history.py      # GitHub commit history fetcher
│
├── tools/
│   ├── k8s_actions.py         # Constrained K8s operations (rollback, scale, restart)
│   └── registry.py            # Maps Nova's JSON tool calls to Python functions
│
├── runbooks/                  # TF-IDF indexed knowledge base
│   ├── *.md                   # Manually authored runbooks
│   ├── pir-*.md               # Auto-generated from resolved incidents (self-learning)
│   └── pir_reports/           # PDF exports of Post-Incident Reports
│
├── dashboard/                 # Glassmorphic Web Dashboard
│   ├── index.html             # Tabbed UI: Incidents + Live Logs + PIR Modal
│   ├── app.js                 # Fetch, render, ANSI parsing, markdown rendering
│   └── style.css              # Dark-mode glass design system
│
└── evaluation_harness/
    └── multi_scenario_test.py # 7-scenario edge case evaluation suite
```

---

## Verification Plan

Because the goal requires high confidence for production readiness, the verification plan is heavily focused on empirical safety testing.

### Automated Evaluation Harness

- **Dataset Generation**: Extract or synthesise realistic incident snapshots — memory leaks, bad PR deployments, DB connection saturation, external API outages, thread deadlocks.
- **Shadow Replay**: The agent runs against all scenarios. Two metrics are measured:
  1. *Root Cause Accuracy* — did it deduce the right issue?
  2. *Action Correctness* — did it propose the right tool?
- **Target**: 90%+ correctness before any live testing. Current result: **7/7 (100%)** across:

| # | Scenario | Expected Tool |
|---|---|---|
| 1 | Bad Deployment OOM | `rollback_deployment` |
| 2 | Traffic Surge | `scale_deployment` |
| 3 | Thread Deadlock | `restart_pods` |
| 4 | Bad DB Config | `rollback_deployment` |
| 5 | Organic Cache Bloat | `restart_pods` |
| 6 | Third-Party API Down | `noop_require_human` |
| 7 | Zero-Shot (No Runbook) | `scale_deployment` |

### Jury Agent Validation

- **Juror Isolation Tests**: Each juror is tested independently against mocked contexts to verify specialisation. Confidence scores and actions are asserted against expected ranges.
- **Escalation Gate Tests**: All 6 gate conditions are exercised individually to confirm each correctly triggers escalation rather than proceeding.
- **Disagreement Handling**: Scenarios with conflicting juror verdicts are run to confirm the Judge resolves them coherently and the gate correctly detects high-confidence disagreement.
- **Anomaly Coverage**: External API, DNS, DB, and security scenarios are verified against the Anomaly Specialist's 3-layer detection to confirm `noop_require_human` is always chosen.

### Local End-to-End Simulation

- Deploy a standard microservice architecture to a local Kubernetes cluster (Minikube).
- Induce faults (e.g., bombard a service until it OOMs, deploy a broken image).
- Verify the agent accurately detects the simulated fault and executes the correct `kubectl` mitigation.
- Verify the jury pipeline fires independently and the Escalation Gate behaves correctly under each fault type.

### Phased Live Rollout

- **Phase 1 — Shadow/Ghost Mode**: Deployed to production, but all action tools return "Simulated Success". The agent posts findings to Slack. Engineers verify correctness while manually fixing the issue.
- **Phase 2 — Read-Only Tooling**: Agent can query DBs and fetch advanced logs autonomously, but mitigations still require a Slack button click.
- **Phase 3 — Full Autonomy**: Approved strictly for a subset of safe, reversible actions (pod restarts, safe auto-scaling) where the jury reaches high-confidence unanimous agreement and the Escalation Gate clears all 6 checks.

---

*Built with Amazon Nova Pro on AWS Bedrock*

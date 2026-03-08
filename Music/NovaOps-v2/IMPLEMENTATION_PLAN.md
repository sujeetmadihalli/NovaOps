# NovaOps v2 — Implementation Plan

## Goal Description

Build a production-grade autonomous SRE incident resolution system that combines two independent LLM reasoning pipelines — a sequential multi-agent War Room and a parallel Jury panel — whose conclusions are compared in a Convergence Check before a policy-governed execution gate makes the final call.

The system prioritises:
1. **Accuracy** — two independent pipelines must agree before automation is allowed
2. **Safety** — every action passes through a risk-scored policy engine with human override always available
3. **Auditability** — every decision step is logged to an append-only audit trail
4. **No silent failures** — disagreement, low confidence, and unknown incidents all route to human review

---

## System Architecture

```
Alert (PagerDuty / Webhook)
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│              EVENT GATEWAY (FastAPI)                     │
│                 POST /webhook/pagerduty                  │
└──────────────────────────┬───────────────────────────────┘
                           │ Background Task
                           ▼
┌──────────────────────────────────────────────────────────┐
│            SHARED CONTEXT AGGREGATORS                    │
│  Logs (CloudWatch)   Metrics (Prometheus)                │
│  K8s Events          GitHub Commits                      │
│  TF-IDF RAG (runbooks + learned PIRs)                   │
└──────────┬─────────────────────────────┬─────────────────┘
           │                             │
           │ full context                │ raw context only
           ▼                             ▼
┌─────────────────────┐     ┌───────────────────────────┐
│  STAGE 1            │     │  STAGE 2                  │
│  WAR ROOM           │     │  JURY VALIDATION          │
│  (Strands DAG)      │     │  (Independent Panel)      │
│                     │     │                           │
│  Triage             │     │  Log Analyst        ─┐    │
│  4 Analysts         │     │  Infra Specialist    ├─→  │
│  Root Cause         │     │  Deploy Specialist   │    │
│  Critic (loop x3)   │     │  Anomaly Specialist ─┘    │
│  Remediation        │     │          │                 │
│  Planner            │     │       Judge LLM            │
│                     │     │       Escalation Gate      │
└─────────┬───────────┘     └───────────┬───────────────┘
          │ proposed_action              │ verdict + confidence
          └──────────────┬──────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│                 STAGE 3: CONVERGENCE CHECK               │
│                                                          │
│  Compare: War Room action  vs  Jury action               │
│                                                          │
│  AGREE   → confidence + 0.15 → proceed to governance    │
│  DISAGREE → confidence - 0.30 → force human review      │
│                                                          │
│  Result logged as CONVERGENCE_CHECK in audit trail       │
└──────────────────────────┬───────────────────────────────┘
                           │ adjusted_confidence
                           ▼
┌──────────────────────────────────────────────────────────┐
│                 GOVERNANCE GATE                          │
│                                                          │
│  Risk score (0-100) = action + severity + conf penalty   │
│  Policy engine (YAML) → ALLOW_AUTO | REQUIRE_APPROVAL    │
│  Append-only audit trail                                 │
└──────────────────────────┬───────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼ ALLOW_AUTO              ▼ REQUIRE_APPROVAL
     Executor runs tool       Slack notification with
     immediately              full dual-pipeline summary
                              Human approves → Executor
```

---

## Component Descriptions

### 1. Event Gateway

FastAPI application at `api/server.py`. Receives `POST /webhook/pagerduty`, starts the 3-stage pipeline as a background task, and returns immediately. Also exposes incident history, governance decisions, audit trails, PIR generation, and Ghost Mode approval endpoints.

### 2. Context Aggregators

Shared by both Stage 1 and Stage 2. Four modules in `aggregator/`:
- **Logs** — AWS CloudWatch `ERROR`/`FATAL` log fetcher with configurable `minutes_back`
- **Metrics** — Prometheus CPU/memory saturation queries
- **K8s State** — pod events, OOMKills, CrashLoopBackOff via Kubernetes API
- **GitHub History** — recent commits and PRs merged to the affected service

A TF-IDF RAG layer (`agents/knowledge_base.py`) scores runbooks and PIR documents against the alert and injects the best match as context.

### 3. Stage 1 — War Room (AWS Strands GraphBuilder)

**File:** `agents/graph.py`, entry point `agents/main.py`

A directed acyclic graph of 7 specialist agents running on Amazon Nova 2 Lite:

| Agent | Role | Sees |
|---|---|---|
| Triage | Classifies domain (6 types), severity (P1-P4), service | Raw alert text |
| Log Analyst | Error patterns, OOM, stack traces | Triage output + logs |
| Metrics Analyst | CPU/memory saturation, trends | Triage output + metrics |
| K8s Inspector | Pod events, OOMKills, crash loops | Triage output + K8s state |
| GitHub Analyst | Recent deployments, commit patterns | Triage output + commits |
| Root Cause Reasoner | Synthesises all analyst findings into ranked hypotheses | All 4 analyst outputs |
| Critic | Adversarially challenges the hypothesis — pass or reject (max 3 loops) | All above |
| Remediation Planner | Proposes one of 4 actions with typed parameters | All above |

All outputs are validated against typed dataclasses in `agents/schemas.py`. Validation failures trigger re-prompting. All findings written to `plans/{incident_id}/findings/`.

### 4. Stage 2 — Jury Validation (Independent Blind Panel)

**Files:** `Agent_Jury/`

Four specialist jurors analyse the **raw incident context only** — they never see the War Room's Triage classification or analyst findings. This preserves full independence.

| Juror | Specialisation | Mock confidence |
|---|---|---|
| Log Analyst | Error logs, OOM, crash traces, exception patterns | 0.88 |
| Infra Specialist | K8s pod health, CPU/memory, OOMKilled, scaling | 0.91 |
| Deployment Specialist | Git commit timing, config regressions, runbook match | 0.85 |
| Anomaly Specialist | External APIs, DNS, DB, security — 3-layer detection | 0.10 (no anomaly) |

**Anomaly Specialist — 3-Layer Detection:**

| Layer | Method | Covers |
|---|---|---|
| Layer 1 — RAG Signal | Low TF-IDF score → no known runbook | Novel / first-seen errors |
| Layer 2 — Pattern Scan | Regex across raw context | External APIs, DNS, DB, security/auth |
| Layer 3 — LLM Residual | Nova analyses unexplained signals | Unknown or compound root causes |

The Judge LLM synthesises all 4 verdicts. The Escalation Gate runs 6 checks:
1. Jury pipeline crashed
2. Judge confidence < 0.6
3. Any juror confidence = 0.0 (LLM failure)
4. High-confidence jurors disagree on action
5. Anomaly Specialist detected external/unknown categories
6. Judge selected `noop_require_human`

If any check fires, `should_escalate=True` is returned to the Convergence Check.

### 5. Stage 3 — Convergence Check

**File:** `pipeline/convergence.py`

Compares the War Room's proposed action against the Jury's proposed action:

```
Base confidence: extracted from war_room.critic → root_cause → default 0.5

AGREE  (same tool, jury not escalating):
  adjusted = min(1.0, base + 0.15)
  confidence_source = "convergence_agreement"

DISAGREE (different tool OR jury escalating):
  adjusted = max(0.0, base - 0.30)
  confidence_source = "convergence_disagreement"
```

The adjusted confidence and full convergence summary are logged to the audit trail as `CONVERGENCE_CHECK` and passed to the Governance Gate via the `incident` dict.

### 6. Governance Gate

**File:** `governance/gate.py`

Single control plane for all execution. Two entry points:
- `evaluate()` — called at end of every investigation, reads `convergence.adjusted_confidence` when present
- `approve_and_execute()` — called via `POST /api/incidents/{id}/approve`, logs `HUMAN_OVERRIDE`

Policy engine (`governance/policies/default.yaml`) evaluates ordered rules. First match wins. Risk score combines action weight + severity weight + confidence penalty.

**Nothing executes outside this gate.**

---

## Module Structure

```
NovaOps-v2/
│
├── agents/                    War Room pipeline
│   ├── graph.py               Strands GraphBuilder DAG
│   ├── main.py                Entry point: Stage 1 → Stage 2 → Stage 3 → Gate
│   ├── schemas.py             Typed dataclasses for all agent outputs
│   ├── artifacts.py           Filesystem artifact persistence
│   ├── prompts.py             Modular system prompts per agent
│   ├── models.py              BedrockModel abstraction (mock-aware)
│   ├── tracing.py             Observability hooks
│   ├── knowledge_base.py      TF-IDF RAG with skill-based retrieval
│   └── pir_generator.py       Post-Incident Report generation
│
├── Agent_Jury/                Jury Validation pipeline (Stage 2)
│   ├── jury_orchestrator.py   Entry: OBSERVE → DELIBERATE → JUDGE → GATE
│   ├── judge.py               Judge LLM: synthesises 4 verdicts
│   ├── escalation_gate.py     6-check safety gate
│   └── jurors/
│       ├── base_juror.py      Base class: LLM invocation, JSON parsing
│       ├── log_analyst.py     Juror 1: error logs, OOM, crash traces
│       ├── infra_specialist.py      Juror 2: K8s health, CPU/memory
│       ├── deployment_specialist.py Juror 3: git commits, config regressions
│       └── anomaly_specialist.py    Juror 4: 3-layer anomaly detection
│
├── agent/                     Jury's Bedrock client
│   └── nova_client.py         Direct boto3 wrapper for Amazon Nova Pro
│
├── pipeline/                  Hybrid integration layer
│   └── convergence.py         War Room vs Jury agreement check
│
├── aggregator/                Shared context extraction (both pipelines)
│   ├── logs.py                CloudWatch log fetcher
│   ├── metrics.py             Prometheus metrics
│   ├── kubernetes_state.py    K8s pod events
│   └── github_history.py      GitHub commit history
│
├── governance/                Policy engine and audit
│   ├── gate.py                GovernanceGate (evaluate + approve_and_execute)
│   ├── policy_engine.py       YAML rule evaluator, risk scorer
│   ├── audit_log.py           Append-only audit.jsonl writer
│   ├── report.py              Human-readable governance report generator
│   └── policies/default.yaml  Risk thresholds and policy rules
│
├── tools/                     Safe execution sandbox
│   ├── executor.py            RemediationExecutor with safety validation
│   ├── k8s_actions.py         Constrained K8s operations
│   ├── investigation.py       Strands @tool wrappers for War Room agents
│   └── retrieve_knowledge.py  Knowledge retrieval for domain skills
│
├── api/                       FastAPI server
│   ├── server.py              All endpoints
│   ├── slack_notifier.py      Ghost Mode Slack payloads
│   └── history_db.py          SQLite incident history
│
├── skills/                    Domain-specific playbooks (6 domains)
│   ├── domains/oom/
│   ├── domains/traffic_surge/
│   ├── domains/deadlock/
│   ├── domains/config_drift/
│   ├── domains/dependency_failure/
│   ├── domains/cascading_failure/
│   └── _shared/triage/, _shared/escalation/
│
├── evaluation/                Scenario harness
│   ├── runner.py              Orchestrates 15 test scenarios
│   └── scenarios.py           Scenario definitions across 6 domains
│
└── tests/                     37 unit tests
```

---

## Verification Plan

### Sanity Tests (automated)
- **Syntax check** — all new and modified files parse cleanly (`ast.parse`)
- **Import check** — all modules resolve without error including cross-pipeline dependencies
- **End-to-end mock run** — `JuryOrchestrator` + `check_convergence` with mock WarRoomResult confirms agreement/disagreement paths produce correct confidence adjustments

Current result: **15/15 syntax, 16/16 imports, mock pipeline PASS**

### Evaluation Harness (15 scenarios)
```bash
NOVAOPS_USE_MOCK=0 python -m evaluation --all
```
Covers all 6 failure domains. Measures root cause accuracy and action correctness.

### Convergence Scenarios to Validate

| Scenario | Expected |
|---|---|
| Both pipelines recommend `rollback_deployment` | AGREE, confidence boosted |
| War Room: `rollback`, Jury: `scale` | DISAGREE, confidence penalised, REQUIRE_APPROVAL |
| Jury Anomaly Specialist detects external API | DISAGREE regardless of War Room action |
| Both recommend `noop_require_human` | AGREE, but governance still REQUIRE_APPROVAL (noop policy) |
| Judge confidence < 0.6 | Jury escalates → DISAGREE |

### Phased Live Rollout

- **Phase 1 — Shadow Mode**: All tools return "Simulated Success". Both pipelines post findings to Slack. Engineers verify while manually fixing.
- **Phase 2 — Read-Only Tooling**: Agents can query logs autonomously, mitigations still require approval.
- **Phase 3 — Full Autonomy**: Only when War Room and Jury agree with high confidence AND governance policy is `ALLOW_AUTO`. Current qualifying condition: P3/P4 + restart/scale + adjusted_confidence >= 0.75.

---

*Built with Amazon Nova 2 Lite on AWS Bedrock — Amazon Nova AI Hackathon 2026*

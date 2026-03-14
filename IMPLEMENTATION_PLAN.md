# NovaOps v2 — Implementation Plan

**Status:** ✅ DEPLOYMENT READY (Updated: March 13, 2026 - Jury Concurrency + Convergence Guard)
**Branch:** nova-agent-3 (selective merge from main complete)
**Sanity Test:** All tests PASSED (10 verification categories, 16 routes, 7 policies, zero breaking changes)

---

## March 13, 2026 Delta (Codex implementation)

Completed changes:
1. Jury deliberation now runs in parallel with timeout isolation using `ThreadPoolExecutor` in `Agent_Jury/jury_orchestrator.py`.
2. Jury GitHub repo context is now configurable:
   - `SERVICE_REPO_MAP` environment variable supports service-to-repo mapping.
   - webhook `metadata.github.owner/repo` overrides mapped defaults per incident.
3. Governance now hard-gates convergence disagreement/escalation in `governance/gate.py`:
   - if `convergence.agree == false` OR jury escalation reasons exist, decision is forced to `REQUIRE_APPROVAL`.

Verification completed:
1. Targeted tests: `tests.test_jury_orchestrator_logic`, `tests.test_governance_gate_logic` passed.
2. Full suite sanity: `python -m unittest discover -s tests -v` passed (`48 tests`, `OK`).

---

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

## Merge Integration Summary (aws-sim + main→v2)

### Phase 1 — aws-sim Merge (Jury System & Governance) ✅
**Integrated from aws-sim branch:**
- `Agent_Jury/` — 4 specialist jurors (Log Analyst, Infra Specialist, Deployment Specialist, Anomaly Specialist) + Judge synthesis
- `governance/` — Policy engine with risk scoring, audit log, governance gate
- `pipeline/convergence.py` — War Room vs Jury agreement/disagreement logic with confidence adjustment
- Full dual-pipeline validation with zero breaking changes to War Room (`agents/graph.py`)

**Status:** ✅ All imports validated, governance policies loaded (7 default rules), audit trail functional

### Phase 2 — Selective Merge from main→v2 (PIR, PDF, Runbooks) ✅
**5-Step Additive Merge (completed successfully):**

| Step | Component | Status | Impact |
|---|---|---|---|
| 1 | Copy 6 runbooks | ✅ DONE | 542 unique terms indexed by TF-IDF RAG, 7 total runbooks (6 imported + 1 demo) |
| 2 | Port `pdf_generator.py` | ✅ DONE | PIRPDFGenerator imports successfully, reportlab>=4.0 confirmed in requirements.txt |
| 3 | Enhance `pir_generator.py` | ✅ DONE | Signature changed to `Tuple[str, str\|None]` with LLM generation + PDF export, graceful fallback |
| 4 | Patch `api/server.py` | ✅ DONE | POST /api/incidents/{id}/report now returns `{report: str, pdf_path: str\|None}` |
| 5 | Enhance `knowledge_base.py` | ✅ DONE | Layer 2 keyword overlap detection prevents duplicate runbook creation (3+ keyword threshold) |

**Quality Gates:**
- ✅ No breaking changes to agents/graph.py (War Room untouched)
- ✅ No breaking changes to Agent_Jury/ (Jury system untouched)
- ✅ No breaking changes to governance/ (Policy engine untouched)
- ✅ Type safety verified (Tuple[str, str|None] correctly unpacked)
- ✅ Error handling (PDF/LLM failures degrade gracefully to text-only)
- ✅ All 16 API routes functional, pdf_path in response JSON
- ✅ Database schema includes report_path column with UNIQUE incident_id constraint
- ✅ Zero runtime errors during mock evaluation harness

**Risk Assessment:** ALL LOW or NONE
- PDF overhead only on-demand (triggered by dashboard PIR button)
- No hot-path impacts (War Room and Jury execution unchanged)
- Runbook corpus immutable (gitignore prevents commits)

### Files Modified (3)
1. **agents/pir_generator.py** — Added LLM generation + PDF export, tuple return
2. **api/server.py** — Updated POST /api/incidents/{id}/report for tuple unpacking + pdf_path response
3. **agents/knowledge_base.py** — Layer 2 keyword overlap detection for runbook matching

### Files Added (1)
1. **agents/pdf_generator.py** — Ported from main (reportlab integration)

### Assets Copied (6 Runbooks)
From: `e:\Nova Hackathon\Nova main\NovaOps\runbooks\`
To: `e:\Nova Hackathon\NOVA-GOVERNANCE-BRANCH\NovaOps\Music\NovaOps-v2\runbooks\`

---

## Verification & Deployment Readiness

### Final Sanity Check (Opus) ✅ PASSED
**10 Verification Categories:**
1. ✅ Type Contracts: Tuple[str, str|None] correct, single call site verified
2. ✅ Architectural Boundaries: No circular dependencies, clean unidirectional flow
3. ✅ Convergence Logic: +0.15 agreement, -0.30 disagreement, UNCHANGED
4. ✅ API Routes: 15 functional routes (11 explicit + 3 FastAPI auto + 1 dashboard)
5. ✅ Database: Schema includes incident_id (UNIQUE), domain, severity, report_path
6. ✅ Knowledge Base: 7 runbooks indexed, Layer 1 (TF-IDF) + Layer 2 (keyword overlap) working
7. ✅ Error Handling: PDF failures graceful, LLM failures fallback to template, fail-fast on missing deps
8. ✅ Governance: Policy evaluation order correct, convergence confidence fed into policies, noop override working
9. ✅ Syntax: All 4 modified/added files pass AST parsing
10. ✅ Risk Assessment: ALL LOW or NONE — PDF overhead only on-demand, no hot-path impacts

**Recommendation:** ✅ READY FOR DEPLOYMENT

### Deployment Checklist
- [x] All dependencies installed (`strands-agents`, `reportlab`, `boto3`, etc.)
- [x] `.env` file configured with AWS credentials
- [x] SQLite history.db schema initialized with UNIQUE constraint
- [x] Runbook corpus indexed (7 files, 542 terms)
- [x] Governance policies loaded (default.yaml, 7 rules)
- [x] Mock mode configurable via `NOVAOPS_USE_MOCK` environment variable
- [x] Docker Compose configured (LocalStack + API)
- [x] Evaluation harness validated (15 scenarios across 6 failure domains)

---

---

## Phase 3 — Dashboard & Docker Hardening ✅ (March 11, 2026)

### Dashboard Fixes
| Fix | File | Detail |
|---|---|---|
| Dynamic win rate | `dashboard/app.js` | `updateWinRate()` computes automated tool % dynamically; was hardcoded `100%` |
| Win rate element | `dashboard/index.html` | `id="win-rate"` placeholder `—`; `?v=2` cache-buster on script tag |
| Refresh button spin | `dashboard/app.js` | `fa-spin` applied to `<i>` element (not the `<button>`); also calls `fetchLogs()` when on logs tab |
| Root redirect | `api/server.py` | `GET /` returns `RedirectResponse` to `/dashboard/` |
| README_RUN.md | `README_RUN.md` | Rewritten for single-server setup on port 8082 (removed outdated two-server instructions) |

### How win rate is calculated
Win rate = incidents with automated tool (`rollback_deployment`, `scale_deployment`, `restart_pods`) / total incidents × 100%.
Incidents with `noop_require_human` or `unknown` tool do not count as automated wins.

### Docker
- `Dockerfile` exposes port `8000` (container internal) — correct
- `docker-compose.yml` maps `"8082:8000"` (host:container) — access via `http://localhost:8082` on host
- `NOVAOPS_USE_MOCK=1` added to `docker-compose.yml` environment — no Bedrock credentials required for local testing
- Do NOT change Dockerfile EXPOSE to 8082; the port mapping in compose handles it

### Clearing old incidents
`IncidentHistoryDB` is held in memory at module level. Deleting `history.db` from disk alone is NOT enough; a full server restart is required.
```powershell
# Stop server first, then:
Remove-Item history.db -Force -ErrorAction SilentlyContinue
Remove-Item plans -Recurse -Force -ErrorAction SilentlyContinue
# Restart server, then Ctrl+Shift+R in browser
```

---

*Built with Amazon Nova 2 Lite on AWS Bedrock — Amazon Nova AI Hackathon 2026*
*Dual-Pipeline Merge Completed: aws-sim (Jury) + main (PIR/PDF/Runbooks) → nova-agent-3/v2*

# NovaOps v2 - Project Context

## Project Overview

NovaOps v2 is an autonomous multi-agent SRE war room powered by Amazon Nova 2 Lite. It responds to production alerts end-to-end: triages the incident, dispatches specialist analysts in parallel, reasons over findings, validates through an independent blind jury, gates actions through a policy engine, and escalates critical incidents via outbound phone calls using Amazon Connect + Nova real-time voice conversation.

## Core Components

### 1. War Room Agents (`/agents`)

Multi-agent investigation pipeline built on AWS Strands Agents SDK.

- `graph.py`: Orchestration graph -- Triage, 4 parallel analysts, Root Cause Reasoner, Critic (max 3 loops), Remediation Planner.
- `main.py`: Entry point -- runs War Room, Jury, Convergence Check, and Governance Gate.
- `schemas.py`: Typed output schemas with validation (TriageOutput, AnalystFindings, RootCauseOutput, CriticOutput, RemediationPlan).
- `artifacts.py`: Writes structured findings to `plans/{incident_id}/`.
- `pir_generator.py` + `pdf_generator.py`: Post-Incident Report generation (Markdown + PDF).

### 2. Jury Validation (`/Agent_Jury`)

Independent blind panel that never sees the War Room's reasoning.

- `jury_orchestrator.py`: Runs 4 specialist jurors in parallel via `ThreadPoolExecutor` with per-juror timeout isolation.
- `jurors/`: Log Analyst, Infra Specialist, Deployment Specialist, Anomaly Specialist.
- `escalation_gate.py`: 6-check safety gate (pipeline failure, low confidence, juror disagreement, anomaly detection, noop escalation).

### 3. Pipeline (`/pipeline`)

- `convergence.py`: Compares War Room vs Jury actions. Agreement boosts confidence (+0.15), disagreement penalizes (-0.30).

### 4. Governance (`/governance`)

- `gate.py`: Single control plane -- evaluates policies, computes risk scores, enforces hard guards (convergence disagree, jury escalation), manages execution.
- `policy_engine.py`: Loads YAML rules, first-match policy evaluation, risk score calculation (action + severity + confidence).
- `audit_log.py`: Append-only event log (`audit.jsonl`).

### 5. API Server (`/api`)

FastAPI backend handling alerts, approvals, and escalation.

- `server.py`: Webhook endpoint, `trigger_agent_loop()` background task, approval endpoint, voice escalation integration.
- `history_db.py`: Dual-backend incident storage (SQLite local / DynamoDB Docker).
- `slack_notifier.py`: Ghost Mode notifications with Approve/Reject buttons + critical escalation fallback.
- `escalation_policy.py`: Classifies incidents as critical vs normal (severity + risk score thresholds).
- `voice_summary.py`: Builds TTS briefing scripts and Nova system prompts from incident data.
- `connect_caller.py`: Amazon Connect outbound call wrapper with mock mode.

### 6. Lambda Handlers (`/lambda_handlers`)

- `nova_connect_handler.py`: Lex V2 fulfillment Lambda -- bridges phone caller speech to Nova real-time via `bedrock.converse()`, detects verbal approval/rejection, triggers the NovaOps approve API.

### 7. Data Aggregators (`/aggregator`)

- Log, metric, Kubernetes, and GitHub data fetchers with live + mock implementations.

### 8. Tools (`/tools`)

- `executor.py`: RemediationExecutor -- validates and executes K8s actions.
- `k8s_actions.py`: Kubernetes API wrappers (rollback, restart, scale) with mock mode.
- `retrieve_knowledge.py`: RAG knowledge retrieval from Bedrock Knowledge Bases or local runbooks.

### 9. Dashboard (`/dashboard`)

Vue.js frontend UI showing live incidents, agent telemetry, governance decisions, and PIR reports.

### 10. Skills (`/skills`)

Domain-specific playbooks for oom, traffic_surge, deadlock, config_drift, dependency_failure, cascading_failure.

## Workflow

1. **Trigger**: Alert arrives via `POST /webhook/pagerduty`.
2. **Investigation**: War Room dispatches Triage + 4 parallel analysts + Root Cause Reasoner + Critic.
3. **Validation**: Independent Jury deliberates on raw incident context only.
4. **Convergence**: War Room and Jury actions are compared; confidence is adjusted.
5. **Governance**: Policy engine evaluates risk score + policies; decides ALLOW_AUTO or REQUIRE_APPROVAL.
6. **Escalation**: Critical incidents (P1 / risk >= 85) trigger an outbound phone call via Amazon Connect. Nova real-time AI converses with the on-call engineer. Non-critical incidents get Slack Ghost Mode notification.
7. **Approval**: Engineer approves verbally (phone) or via Slack/dashboard. Approval routes through GovernanceGate with full audit trail.
8. **Execution**: Remediation action executed via K8s API.
9. **Reporting**: PIR generated, PDF uploaded to S3, artifacts saved to `plans/{incident_id}/`.

## Key Files

- `start_system.sh`: Launch full stack (Docker, LocalStack, API, dashboard).
- `docker-compose.yml`: Local stack definition.
- `run_simulated_incidents.sh`: Fire 7 test incidents into the pipeline.
- `run_live_k8s_test.sh`: Live OOM test with Minikube + voice call.
- `sonic_call.py`: Standalone voice call CLI (local mic/speaker via Bedrock).
- `trigger_test_incidents.py`: Incident trigger CLI tool.
- `requirements.txt`: Python dependencies.
- `.env.example`: All environment variables documented.

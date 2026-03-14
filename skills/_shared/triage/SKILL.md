---
name: incident-triage
description: Universal first-response triage for any production incident. Classifies domain, severity, and routes to specialist agents.
---

# Incident Triage Skill

## Step 1: Extract Signal
From the alert payload, extract:
- Service name and namespace
- Alert type (what triggered it)
- Timestamp and duration
- Any error messages in the alert body

## Step 2: Classify Domain
Match alert keywords against `skills/_meta/index.yaml` to determine domain.
If multiple domains match, select the one with the most keyword hits.
If no domain matches, classify as `unknown` and load escalation skill.

## Step 3: Assess Severity
- **P1 (Critical)**: Service fully down, customer-facing impact
- **P2 (High)**: Degraded performance, partial impact
- **P3 (Medium)**: Internal service issues, no customer impact
- **P4 (Low)**: Warnings, potential future issues

## Step 4: Route
Based on domain classification:
1. Select which specialist agents to activate
2. Load the domain-specific SKILL.md for each agent
3. Fan out to parallel investigation

## Output Format
```json
{
  "domain": "oom|traffic_surge|deadlock|config_drift|dependency_failure|cascading_failure|unknown",
  "severity": "P1|P2|P3|P4",
  "agents_to_activate": ["log_analyst", "metrics_analyst", "k8s_inspector"],
  "skill_path": "skills/domains/{domain}/",
  "initial_hypotheses": ["hypothesis 1", "hypothesis 2"]
}
```

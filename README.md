# NovaOps: Autonomous Production Incident Resolution Agent

This repository contains the source code for an autonomous, event-driven agent capable of resolving production incidents.
It uses Amazon Nova for reasoning across large contexts (logs, metrics, and state) and executes defined runbook steps in a secure sandbox.

## Structure
- `api/`: Webhook receivers and background task triggers.
- `aggregator/`: Context gathering from various sources (Logs, Metrics, K8s, GitHub).
- `agent/`: Orchestration loop leveraging LLM reasoning.
- `tools/`: Constrained execution actions (scaling, rollbacks, etc.).
- `evaluation_harness/`: Framework to test the agent on historical incidents.

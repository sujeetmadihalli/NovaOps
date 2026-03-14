# NovaOps Incident Agent - Project Context

## Project Overview
NovaOps is an autonomous incident response agent designed to detect, analyze, and resolve system failures in a Kubernetes/microservices environment. It integrates with Prometheus for metrics and utilizes a RAG (Retrieval-Augmented Generation) approach for incident analysis.

## Core Components

### 1. Agent (`/agent`)
The brain of the system.
- `orchestrator.py`: Manages the lifecycle of an incident.
- `nova_client.py`: Interface for AI model interactions.
- `prom_client.py`: Fetches metrics from Prometheus.
- `k8s_client.py`: Interacts with the Kubernetes cluster for logs and state.

### 2. Event Gateway / API (`/api`)
Handles incoming webhooks and provides data for the dashboard.
- `webhook_handler.py`: Receives alerts (e.g., from PagerDuty/Prometheus).
- `history_db.py`: Stores incident history and analysis results.

### 3. Dashboard (`/dashboard`)
A React-based UI to visualize:
- Live incidents and their status.
- Agent's step-by-step reasoning and analysis.
- Telemetry and logs.

### 4. Dummy Service (`/dummy-service`)
A FastAPI application used for testing and demonstrations.
- Contains a `/memory-leak` endpoint to simulate OOM (Out Of Memory) errors.
- Deployed via `k8s.yaml`.

### 5. Aggregator & Tools (`/aggregator`, `/tools`)
- Services for log aggregation and utility scripts for system maintenance.

## Key Files
- `start_novaops.sh`: Main entry point to launch the entire system using Docker Compose.
- `docker-compose.yml`: Defines the local stack (Agent, API, Dashboard, Prometheus).
- `simulate_incident.sh`: [NEW] All-in-one script to break the `dummy-service` and trigger the agent via webhooks.
- `test_alert.sh`: Simple script to send a test alert payload.

## Workflow
1. **Trigger**: An alert is sent to the API webhook.
2. **Analysis**: The Agent fetches logs and metrics related to the service.
3. **Reasoning**: The AI model analyzes the data to find the root cause.
4. **Resolution**: The Agent proposes or executes a runbook fix.
5. **Visualization**: All steps are visible in real-time on the Dashboard.

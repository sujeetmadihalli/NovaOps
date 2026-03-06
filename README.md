# NovaOps: Autonomous Production Incident Resolution Agent

**NovaOps** is an autonomous, event-driven agent built to transition production tier incidents from "alerting" directly to "resolving." Designed around the massive 300K context window of **Amazon Nova Pro**, this tool ingests sprawling diagnostic data (logs, metrics, git histories) and executes safe, constrained remediations.

Currently, the repository is configured to run as a **Live End-to-End Hackathon Demo**. It deploys a local Kubernetes cluster, installs Prometheus, runs an intentionally vulnerable microservice, and uses the real Amazon Nova API to resolve the injected incidents.

---

## System Architecture

The architecture is strictly separated into **Read (Observation)** and **Write (Execution)** boundaries to guarantee safety.

1. **Event Gateway (`api/`)**: A FastAPI webhook receiver listening for PagerDuty or OpsGenie alerts. By design, it relies on Prometheus to poll the cluster every 15 seconds. If a metric stays bad for a full 1 or 2 minutes, Prometheus finally pushes a Webhook to wake up the Agent. This deliberate delay prevents false alarms from triggering unnecessary incident responses.
2. **Context Aggregators (`aggregator/`)**: Once triggered, these parallelized modules fetch the exact state of the world to build the Amazon Nova prompt payload:
   - **Logs**: OpenSearch/CloudWatch error and fatal traces.
   - **Metrics**: Real-time Prometheus metric saturation (e.g. Memory limits).
   - **GitHub**: Recent commit history.
   - **Kubernetes**: Live pod events (CrashLoopBackoffs, OOMKills).
3. **Knowledge Base (`agent/knowledge_base.py`)**: A RAG setup using ChromaDB that injects proprietary Markdown runbooks (e.g., `runbooks/dummy-service-oom.md`) directly into the LLM context.
4. **Reasoning Engine (`agent/orchestrator.py`)**: The Amazon Nova-powered core that digests the context, formulates a hypothesis, and decides on a tool to invoke.
5. **Execution Sandbox (`tools/`)**: A heavily constrained environment. The agent can only call specific, strictly-typed Python functions (like `restart_pods` or `rollback_deployment`).
6. **Ghost Mode (`api/slack_notifier.py`)**: The human-in-the-loop safety net. The agent posts its hypothesis and an "Execute" button to Slack, rather than executing autonomously in this phase of deployment.

---

## Running the Live End-to-End Demo

This repository is pre-configured to run a live demonstration on your local machine using real infrastructure and the live Amazon Nova API.

### 1. Prerequisites
- `minikube` and `kubectl` installed
- `helm` installed (to deploy the Prometheus monitoring stack)
- An AWS Account with Bedrock access to the Amazon Nova Pro model.
- Your AWS keys added to a `.env` file at the root of the project:
  ```env
  AWS_ACCESS_KEY_ID=your_access_key
  AWS_SECRET_ACCESS_KEY=your_secret_key
  AWS_DEFAULT_REGION=us-east-1
  ```
- Initialize your Python environment:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

### 2. Start the Demo Infrastructure
Make sure your Minikube cluster is running (`minikube start`) and the dummy service + prometheus stack are deployed. 
Run the provided bash script to start the local port forwards required for the agent to scrape the live cluster metrics:

```bash
./start_demo.sh
```
*(Leave this terminal window open in the background!)*

### 3. Induce the Production Incident
In a new terminal, intentionally trigger the memory leak on the dummy victim application to simulate a massive usage spike:

```bash
curl http://localhost:8080/memory-leak
# (Run this 2 or 3 times to guarantee a pod crash)
```

### 4. Trigger the Amazon Nova Agent
Rather than waiting 3 minutes for the Prometheus Webhook to naturally fire the Event Gateway, you can instantly execute the agent against the live infrastructure to demonstrate the ReAct loop:

```bash
PYTHONPATH=. venv/bin/python evaluation_harness/test_agent_accuracy.py
```

**Expected Result:**
The agent will pull the live Memory telemetry from Prometheus, identify the `dummy-service` saturation, retrieve the `dummy-service-oom` runbook from the Vector database, and generate an interactive "Ghost Mode" Slack payload proposing a safe `restart_pods` mitigation plan.

---

## Project Structure

```text
incident-agent/
│
├── .env                       # (User created) AWS Credentials for Nova
├── requirements.txt           # Python dependencies (Chromadb, boto3, fastapi)
├── start_demo.sh              # Bash script to port-forward localhost to Minikube
├── Dockerfile                 # (Optional) Container build for the agent itself
│
├── api/                       # FastApi Endpoints & Webhooks
│   ├── server.py              # PagerDuty webhook receiver (Trigger)
│   └── slack_notifier.py      # Generates interactive Slack JSON payloads
│
├── agent/                     # The AWS Bedrock LLM Brain and RAG
│   ├── knowledge_base.py      # ChromaDB Vector Store for Runbooks
│   ├── nova_client.py         # AWS boto3 client connecting to Bedrock Nova Pro
│   └── orchestrator.py        # The ReAct (Reason -> Act) Loop utilizing Nova
│
├── aggregator/                # Context Extraction Pipeline
│   ├── github_history.py      # Interrogates GitHub API for recent commits
│   ├── kubernetes_state.py    # Interrogates local Minikube for Pod crash events
│   ├── logs.py                # Interrogates AWS CloudWatch (or local scrape) for errors
│   └── metrics.py             # Queries local Prometheus for CPU/Memory saturation
│
├── tools/                     # Safe Execution Sandbox for K8s remediation
│   ├── k8s_actions.py         # Heavily constrained subset of minikube kubectl commands
│   └── registry.py            # Maps Novas JSON intents to the Python functions
│
├── runbooks/                  # Markdown files acting as the initial Knowledge Base
│   ├── dummy-service-oom.md   # Runbook mapping memory leaks to a "restart_pods" action
│   └── redis-oom-error.md     # Runbook mapping OOM to a "rollback_deployment" action
│
├── dummy-service/             # The intentional vulnerable microservice
│   ├── main.py                # Python FastAPI app with an explicit memory leak array
│   ├── k8s.yaml               # Kubernetes Deployment and NodePort Service definition
│   ├── Dockerfile             # Local docker build instructions
│   └── requirements.txt       # Uses `prometheus_client` to expose metrics
│
└── evaluation_harness/        
    └── test_agent_accuracy.py # End-to-end trigger script demonstrating the live agent
```

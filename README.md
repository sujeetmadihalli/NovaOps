# NovaOps: Autonomous Production Incident Resolution Agent

**NovaOps** is an autonomous, event-driven agent built to transition production tier incidents from "alerting" directly to "resolving." Designed around the massive 300K context window of **Amazon Nova Pro**, this tool ingests sprawling diagnostic data (logs, metrics, git histories) and executes safe, constrained remediations.

When an engineer is paged at 3 AM, MTTR (Mean Time to Resolution) is often severely delayed by the time it takes the human to orient themselves across Datadog, CloudWatch, GitHub, and Kubernetes dashboards.

NovaOps aggregates this context in milliseconds, reasons via a ReAct loop, and resolves the issue automatically—or hands off a ready-to-execute plan via Slack.

---

## System Architecture

The architecture is strictly separated into **Read (Observation)** and **Write (Execution)** boundaries to guarantee safety in production.

1. **Event Gateway (`api/`)**: A FastAPI webhook receiver listening for PagerDuty or OpsGenie alerts.
2. **Context Aggregators (`aggregator/`)**: Once triggered, these parallelized modules fetch the exact state of the world to build the Amazon Nova prompt payload:
   - **Logs**: OpenSearch/CloudWatch error and fatal traces.
   - **Metrics**: Prometheus/Datadog metric saturation (CPU, Memory, 5xx errors).
   - **GitHub**: Recent commit history to detect bad deployments.
   - **Kubernetes**: Live pod events (CrashLoopBackoffs, OOMKills, Evictions).
3. **Knowledge Base (`agent/knowledge_base.py`)**: A RAG (Retrieval-Augmented Generation) system that injects your company's proprietary Markdown runbooks directly into the LLM context.
4. **Reasoning Engine (`agent/orchestrator.py`)**: The Amazon Nova-powered core that digests the 300K tokens of context, formulates a hypothesis, and decides on a tool to invoke.
5. **Execution Sandbox (`tools/`)**: A heavily constrained environment. The agent does NOT have bash access. It can only call specific, strictly-typed Python functions (like `scale_deployment` or `rollback_deployment`), ensuring the LLM cannot hallucinate a destructive command like dropping a database.
6. **Ghost Mode (`api/slack_notifier.py`)**: The human-in-the-loop safety net. The agent posts its hypothesis and an "Execute" button to Slack, rather than executing autonomously.

---

## Project Structure

```text
incident-agent/
│
├── api/                       # FastApi Endpoints & Webhooks
│   ├── server.py              # PagerDuty webhook receiver
│   └── slack_notifier.py      # 'Ghost Mode' Slack interactivity payload generator
│
├── agent/                     # The LLM Brain
│   ├── knowledge_base.py      # Local RAG for Markdown Runbooks
│   ├── nova_client.py         # Amazon Bedrock client for Nova Pro inference
│   └── orchestrator.py        # The ReAct (Reason -> Act) Loop utilizing Nova
│
├── aggregator/                # Context Extraction Pipeline
│   ├── logs.py                # Fetches AWS CloudWatch / OpenSearch logs
│   ├── metrics.py             # Fetches Prometheus saturation metrics
│   ├── kubernetes_state.py    # Fetches recent Kube-API pod events
│   └── github_history.py      # Fetches recent merged PRs/Commits
│
├── tools/                     # Safe Execution Sandbox
│   ├── registry.py            # Maps LLM JSON intents to underlying python functions
│   └── k8s_actions.py         # The actual constrained remediation logic (scale, rollback)
│
├── runbooks/                  # Markdown files acting as the Knowledge Base
│   └── redis-oom-error.md     # Example Runbook
│
└── evaluation_harness/        
    └── test_agent_accuracy.py # End-to-end framework to simulate historical PagerDuty payloads
```

---

## Running the Evaluation Harness

To ensure the agent behaves properly and respects sandbox constraints, we use an evaluation harness that mocks a production PagerDuty incident. Currently, the harness mocks a **"Redis Out of Memory"** scenario.

### 1. Requirements

Ensure you have initialized your Python virtual environment and installed requirements:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Test

Run the simulated incident evaluation. This script initializes the agent completely locally (without needing actual AWS credentials or a live Kubernetes cluster) by passing the `use_mock=True` parameter.

```bash
PYTHONPATH=. venv/bin/python evaluation_harness/test_agent_accuracy.py
```

### Expected Output
The console will output the Agent aggregating the mocked context (logs, metrics, git history) and querying the Knowledge Base for the Redis Runbook.

It will then output the final **JSON payload** demonstrating that the Amazon Nova agent correctly deduced the root cause (a recent bad deployment causing memory leaks) and proposed a safe `rollback_deployment` action to resolve it, which is immediately sent to the Ghost Mode Slack webhook.

---

## Running via Docker (Hackathon Demo)

For the easiest demonstration setup without managing local python environments, you can run NovaOps entirely within a Docker container. 

The image is optimized (using `python:3.10-slim` and CPU-only ML wheels) to ensure it builds quickly.

### 1. Build the Image
```bash
docker build -t novaops-agent .
```

### 2. Run the Container
```bash
# We map port 8000 to the host so the FastAPI webhook receiver is exposed
docker run -p 8000:8000 novaops-agent
```

Once running, the server is listening for incident payloads on `http://localhost:8000`.

---

##  Running the Live End-to-End Hackathon Demo

For the ultimate presentation, you can run the entire agent against a **live local Kubernetes cluster** and **real Prometheus metrics**, connected directly to the **Amazon Nova API** in the cloud. We have prepared an intentionally vulnerable `dummy-service` inside a `minikube` cluster to demonstrate the ReAct loop in real time.

### 1. Prerequisites
- `minikube` and `kubectl` installed
- `helm` installed (to deploy the Prometheus monitoring stack)
- An AWS Account with Bedrock access to the Amazon Nova Pro model.
- Your AWS keys added to the `.env` file at the root of the project:
  ```
  AWS_ACCESS_KEY_ID=your_access_key
  AWS_SECRET_ACCESS_KEY=your_secret_key
  AWS_DEFAULT_REGION=us-east-1
  ```

### 2. Start the Demo Services
Make sure your Minikube cluster is running (`minikube start`) and the dummy service + prometheus stack are deployed. 
Run the provided bash script to start the local port forwards required for the agent to scrape the live cluster metrics:

```bash
./start_demo.sh
```
*(Leave this terminal window open in the background!)*

### 3. Induce the Production Incident!
In a new terminal, intentionally trigger the memory leak on the dummy victim application to simulate a massive usage spike:

```bash
curl http://localhost:8080/memory-leak
# (Run this 2 or 3 times to guarantee a Prometheus OOM warning)
```

### 4. Wake up the Amazon Nova Agent
Instantly execute the agent against the live infrastructure so it can deduce the root cause and propose the mitigation.

```bash
PYTHONPATH=. venv/bin/python evaluation_harness/test_agent_accuracy.py
```

The agent will pull the live CPU/Memory telemetry from Prometheus, identify the `dummy-service` saturation, retrieve the appropriate `dummy-service-oom.md` runbook from the Vector database, and generate an interactive "Ghost Mode" Slack payload proposing a safe `restart_pods` mitigation plan.

---

## From Ghost Mode to Full Autonomy

For enterprise adoption, **NovaOps** is designed for a phased rollout:
- **Phase 1 (Shadow Mode)**: Live data is ingested, but the agent only posts its findings to Slack. Human engineers verify the logic.
- **Phase 2 (Ghost Mode - Current implementation)**: The agent has read-only tooling and posts a remediation plan to Slack with an **"Approve Execution"** button. The human clicks to authorize the fix.
- **Phase 3 (Full Autonomy)**: The Slack gateway is bypassed for trusted, low-risk tools (e.g., restarting pods), fully automating resolution at 3 AM.

import json
import logging
import re
from typing import Dict, Any

from agent.nova_client import NovaClient
from aggregator.logs import LogsAggregator
from aggregator.metrics import MetricsAggregator
from aggregator.kubernetes_state import KubernetesStateAggregator
from aggregator.github_history import GithubHistoryAggregator
from agent.knowledge_base import KnowledgeBaseRAG

logger = logging.getLogger(__name__)

# The rigorous system prompt
SYSTEM_PROMPT = """
You are an Autonomous SRE incident resolution agent.
You are equipped with Amazon Nova's extended reasoning capabilities.
You will receive a massive dump of context including Recent Logs, Metrics, Kubernetes Cluster State, Recent Deployments, and Relevant Runbooks.

Analyze the context to determine the root cause of the outage.
Do not hallucinate.

1. First, think step-by-step about the root cause inside <thinking> tags.
2. Then, output your response STRICTLY as a JSON block wrapped in ```json ... ``` with the following structure:
```json
{
    "root_cause_analysis": "string explaining exactly why the service failed based on the logs and metrics",
    "action": {
        "tool": "tool_name_here",
        "parameters": { ... tool specific kwargs ... }
    }
}
```

Available Tools:
1. `rollback_deployment` - Rolls back a recent bad code change. Use when a recent deployment is clearly the cause. (Params: service_name)
2. `scale_deployment` - Increases replicas to handle load. Use when CPU is saturated and the service is healthy but overwhelmed. (Params: service_name, target_replicas)
3. `restart_pods` - Clears deadlocks or cache by restarting pods. Use when code is fine but pods are in a bad runtime state. (Params: service_name)
4. `query_more_logs` - Fetches older logs and re-invokes you with the enriched context. Use ONLY when the root cause is genuinely ambiguous and older history would change the diagnosis. Do NOT use if the error is already clear. You have 3 attempts total — query_more_logs consumes one of them, so you will have at most 2 remaining attempts to commit to a final action after receiving the extended logs. (Params: service_name, minutes_back)
5. `noop_require_human` - Hand off to a human SRE. Use when: the incident is caused by an external/third-party service outage, a DNS/network failure outside the cluster, a security breach, an unknown error type that none of the other tools can fix, or the situation is too complex to auto-remediate safely.

If the context already contains a section labelled "EXTENDED LOGS", query_more_logs has already run — do NOT choose it again. Commit to a remediation action on this attempt.
"""

VALID_TOOLS = ["rollback_deployment", "scale_deployment", "restart_pods", "query_more_logs", "noop_require_human"]

class AgentOrchestrator:
    def __init__(self, mock_sensors: bool = True, mock_llm: bool = False):
        self.mock_sensors = mock_sensors
        self.mock_llm = mock_llm
        
        # The LLM now defaults to hitting the real AWS API
        self.llm = NovaClient(use_mock=self.mock_llm)
        
        # The Aggregators default to Mock so the Hackathon demo is easy to run
        self.logs_agg = LogsAggregator(use_mock=self.mock_sensors)
        self.metrics_agg = MetricsAggregator(use_mock=self.mock_sensors)
        self.k8s_agg = KubernetesStateAggregator(use_mock=self.mock_sensors)
        self.git_agg = GithubHistoryAggregator(use_mock=self.mock_sensors)
        self.rag = KnowledgeBaseRAG()

    def run_incident_resolution(self, alert_name: str, service_name: str, namespace: str = "default") -> Dict[str, Any]:
        """
        The main ReAct loop: Observe -> Reason -> Act.
        With fortified retry loops and self-correction.
        """
        logger.info(f"Waking up agent for alert: {alert_name} on service {service_name}")
        
        # 1. OBSERVE: Aggregate massive context
        logger.info("Aggregating context...")
        logs = self.logs_agg.get_recent_errors(service_name)
        metrics = self.metrics_agg.get_service_metrics(service_name)
        k8s_events = self.k8s_agg.get_pod_events(namespace, service_name)
        commits = self.git_agg.get_recent_commits("org", "repo")
        runbook = self.rag.search_relevant_runbook(alert_name)
        
        base_context = f"""
        --- ALERT ---
        Name: {alert_name}
        Service: {service_name}
        
        --- KNOWLEDGE BASE (RUNBOOK) ---
        {runbook}
        
        --- METRICS ---
        {json.dumps(metrics, indent=2)}
        
        --- KUBERNETES EVENTS ---
        {json.dumps(k8s_events, indent=2)}
        
        --- RECENT COMMITS ---
        {json.dumps(commits, indent=2)}
        
        --- LOGS (ERROR/FATAL) ---
        {json.dumps(logs, indent=2)}
        """
        
        # 2. REASON: Send to Nova with Self-Correction Retry Loop
        logger.info("Sending 300K context to Amazon Nova...")
        
        MAX_RETRIES = 3
        current_context = base_context
        
        for attempt in range(MAX_RETRIES):
            response = self.llm.invoke(SYSTEM_PROMPT, current_context)
            
            if not response["success"]:
                logger.error(f"LLM failure on attempt {attempt+1}: {response.get('error')}")
                if attempt == MAX_RETRIES - 1:
                    return {"status": "failed", "reason": "LLM Invocation Error"}
                continue
                
            raw_content = response["content"]
            
            # Extract JSON block using regex to ignore any <thinking> tags
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw_content, re.DOTALL)
            if not json_match:
                # Try generic matching if they didn't wrap it perfectly
                json_match = re.search(r'(\{.*\})', raw_content, re.DOTALL)
                
            if not json_match:
                logger.warning(f"Attempt {attempt+1}: LLM did not output a recognizable JSON block. Retrying...")
                current_context += f"\n\nERROR IN PREVIOUS ATTEMPT: You did not output valid JSON. Please provide ONLY valid JSON wrapped in ```json tags."
                continue
                
            try:
                decision = json.loads(json_match.group(1))
                
                # Strict Tool Validation Sandbox
                action = decision.get("action", {})
                tool = action.get("tool")
                
                if tool not in VALID_TOOLS:
                    logger.warning(f"Attempt {attempt+1}: LLM hallucinated invalid tool '{tool}'. Forcing self-correction.")
                    current_context += f"\n\nERROR IN PREVIOUS ATTEMPT: You chose an invalid tool '{tool}'. You MUST choose from this exact list: {VALID_TOOLS}."
                    continue

                # ReAct feedback loop: execute query_more_logs and re-reason with enriched context
                if tool == "query_more_logs":
                    minutes_back = action.get("parameters", {}).get("minutes_back", 60)
                    logger.info(f"[ReAct] Agent requested extended logs (minutes_back={minutes_back}). Fetching and re-reasoning...")
                    extended_logs = self.logs_agg.get_recent_errors(service_name, minutes_back=minutes_back)
                    current_context += (
                        f"\n\n--- EXTENDED LOGS (fetched {minutes_back} minutes back per your request) ---\n"
                        f"{json.dumps(extended_logs, indent=2)}\n\n"
                        f"You now have additional log history. Re-analyze and provide a final remediation action. "
                        f"Do NOT choose query_more_logs again — commit to a decision."
                    )
                    continue

                logger.info(f"Agent Hypothesis: {decision.get('root_cause_analysis')}")
                logger.info(f"Agent proposed action: {action}")

                return {
                    "status": "plan_ready",
                    "analysis": decision.get("root_cause_analysis"),
                    "proposed_action": action
                }
                
            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt+1}: JSON parsing failed ({e}). Retrying...")
                current_context += f"\n\nERROR IN PREVIOUS ATTEMPT: Your JSON was malformed. Error details: {e}. Please output strict valid JSON."
                
        logger.error(f"Agent failed to produce a valid action after {MAX_RETRIES} attempts.")
        return {"status": "failed", "reason": "Max retries exceeded evaluating malformed LLM responses."}

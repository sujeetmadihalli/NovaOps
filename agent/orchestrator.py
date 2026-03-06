import json
import logging
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
Do not hallucinate. If you are unsure, request to query more logs.

You must output your response STRICTLY as a JSON object with the following structure:
{
    "root_cause_analysis": "string explaining exactly why the service failed based on the logs and metrics",
    "action": {
        "tool": "tool_name_here",
        "parameters": { ... tool specific kwargs ... }
    }
}

Available Tools:
1. `rollback_deployment` - Rolls back a recent bad code change constraint. (Params: service_name)
2. `scale_deployment` - Increases replicas to handle load. (Params: service_name, target_replicas)
3. `restart_pods` - Clears deadlocks or cache by restarting pods. (Params: service_name)
4. `query_more_logs` - Fetches older logs if current context is insufficient. (Params: service_name, minutes_back)
5. `noop_require_human` - If the situation is too complex or requires database manipulation, use this tool to safely hand off.
"""

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
        """
        logger.info(f"Waking up agent for alert: {alert_name} on service {service_name}")
        
        # 1. OBSERVE: Aggregate massive context
        logger.info("Aggregating context...")
        logs = self.logs_agg.get_recent_errors(service_name)
        metrics = self.metrics_agg.get_service_metrics(service_name)
        k8s_events = self.k8s_agg.get_pod_events(namespace, service_name)
        commits = self.git_agg.get_recent_commits("org", "repo")
        runbook = self.rag.search_relevant_runbook(alert_name)
        
        context_payload = f"""
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
        
        # 2. REASON: Pass to Nova
        logger.info("Sending 300K context to Amazon Nova...")
        response = self.llm.invoke(SYSTEM_PROMPT, context_payload)
        
        if not response["success"]:
            logger.error(f"LLM failure: {response.get('error')}")
            return {"status": "failed", "reason": "LLM Invocation Error"}
            
        try:
            # We enforce JSON output in the prompt
            decision = json.loads(response["content"])
            logger.info(f"Agent Hypothesis: {decision.get('root_cause_analysis')}")
            logger.info(f"Agent proposed action: {decision.get('action')}")
            
            # In purely autonomous mode, we would call the tool execution here.
            # However, for our architecture we will pass this plan to the Slack Ghost Mode notifier.
            return {
                "status": "plan_ready",
                "analysis": decision.get("root_cause_analysis"),
                "proposed_action": decision.get("action")
            }
            
        except json.JSONDecodeError:
            logger.error("LLM did not return proper JSON.")
            return {"status": "failed", "reason": "Malformed LLM output"}

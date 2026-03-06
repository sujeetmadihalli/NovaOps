import os
import sys

# Add the parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import AgentOrchestrator
from api.slack_notifier import SlackNotifier
import json
import time

def run_test_scenario(scenario_name: str, mock_data: dict, expected_tool: str):
    """
    Runs a specific mocked incident scenario against the real Amazon Nova LLM.
    """
    print(f"\n=========================================")
    print(f"SCENARIO: {scenario_name}")
    print(f"=========================================")
    
    # We use mock_sensors=True here because we are intentionally injecting fake scenarios
    # but mock_llm=False so the REAL Amazon Nova evaluates them.
    agent = AgentOrchestrator(mock_sensors=True, mock_llm=False)
    
    # 1. Overwrite the agent's mocked data methods for this specific scenario
    agent.metrics_agg._get_mock_metrics = lambda service: mock_data['metrics']
    agent.k8s_agg._get_mock_events = lambda service: mock_data['k8s_events']
    agent.logs_agg._get_mock_logs = lambda service: mock_data['logs']
    agent.git_agg._get_mock_commits = lambda *args: mock_data['github']
    
    # Overwrite the RAG to ensure it reads the correct runbook for the scenario context
    if "redis" in scenario_name.lower():
        agent.rag.search_relevant_runbook = lambda query: "If an OOM event occurs immediately after a deployment, mitigate immediately using the rollback_deployment tool."
    else:
        agent.rag.search_relevant_runbook = lambda query: "If traffic surges and liveness probes fail, mitigate by using the scale_deployment tool."
    
    # 2. Trigger
    result = agent.run_incident_resolution(
        alert_name=scenario_name,
        service_name="payment-service",
        namespace="prod"
    )
    
    # 3. Evaluate
    print("\n--- LLM JSON RAW DECISION ---")
    print(json.dumps(result, indent=2))
    
    if result.get("status") == "plan_ready":
        tool_chosen = result.get("proposed_action", {}).get("tool")
        if tool_chosen == expected_tool:
            print(f"\n✅ PASS: Agent correctly chose '{tool_chosen}' for {scenario_name}.")
        else:
            print(f"\n❌ FAIL: Expected '{expected_tool}', but Agent chose '{tool_chosen}'.")
    else:
        print(f"\n❌ FAIL: Agent failed to generate a plan.")

def main():
    # ---------------------------------------------------------
    # SCENARIO 1: BAD DEPLOYMENT OOM LOOP
    # ---------------------------------------------------------
    # Should Rollback
    scenario_1 = {
        "metrics": {"cpu_utilization": "Stable", "memory_usage_mb": 4500, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "OOMKilling", "message": "Memory cgroup out of memory", "timestamp": "Now"}],
        "logs": [{"timestamp": "Now", "message": "[FATAL] OutOfMemoryError: Java heap space"}],
        "github": [{"sha": "a1b2c3", "author": "dev", "message": "feat: Bump cache size to 10GB", "date": "10 mins ago"}]
    }
    
    # ---------------------------------------------------------
    # SCENARIO 2: TRAFFIC SURGE (CPU EXHAUSTION)
    # ---------------------------------------------------------
    # Should Scale
    scenario_2 = {
        "metrics": {"cpu_utilization": "99.9%", "memory_usage_mb": 500, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "FailedProbes", "message": "Liveness probe failed: HTTP timeout", "timestamp": "Now"}],
        "logs": [{"timestamp": "Now", "message": "[ERROR] ThreadPoolExecutor exhausted. Rejecting requests."}],
        "github": [{"sha": "x9y8z7", "author": "dev", "message": "fix: typo in readme", "date": "3 days ago"}] # Unrelated commit
    }

    print("STARTING BATCH EVALUATION...")
    print("Testing Amazon Nova's reasoning capabilities across diverse incident signatures.")
    
    run_test_scenario("Redis Bad Deployment Memory Leak", scenario_1, expected_tool="rollback_deployment")
    time.sleep(2) # Give AWS API a breath
    run_test_scenario("Payment Service Traffic Surge", scenario_2, expected_tool="scale_deployment")

if __name__ == "__main__":
    main()

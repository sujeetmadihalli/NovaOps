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
    if "redis oom" in scenario_name.lower() or "cache bloat" in scenario_name.lower():
        agent.rag.search_relevant_runbook = lambda query: "If an OOM event occurs immediately after a deployment, mitigate by rolling back. IF NO DEPLOYMENT OCCURRED, cache is bloated and you should restart the pods to flush the heap."
    elif "surge" in scenario_name.lower():
        agent.rag.search_relevant_runbook = lambda query: "If traffic surges and liveness probes fail, mitigate by using the scale_deployment tool."
    elif "deadlock" in scenario_name.lower():
        agent.rag.search_relevant_runbook = lambda query: "If threads are deadlocked and CPU is at 0%, but the service is unresponsive, restart the pods to clear the race condition."
    elif "typo" in scenario_name.lower() or "database connection" in scenario_name.lower():
        agent.rag.search_relevant_runbook = lambda query: "If the application refuses to start instantly after a deployment due to 'ConnectionRefused' to the database, use rollback_deployment to undo the bad configuration."
    elif "zero-shot" in scenario_name.lower():
        agent.rag.search_relevant_runbook = lambda query: "No relevant runbook found for this issue."
    else:
        agent.rag.search_relevant_runbook = lambda query: "No specific runbook found for this issue."
    
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
    
    # ---------------------------------------------------------
    # SCENARIO 3: THREAD DEADLOCK (ZERO CPU EXHAUSTION)
    # ---------------------------------------------------------
    # Should Restart Pods (Because scaling a deadlocked app just creates more deadlocked pods)
    scenario_3 = {
        "metrics": {"cpu_utilization": "0.1%", "memory_usage_mb": 200, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "Unhealthy", "message": "Readiness probe failed", "timestamp": "Now"}],
        "logs": [{"timestamp": "Now", "message": "[WARN] Thread 4 waiting to acquire lock held by Thread 2. [FATAL] Deadlock detected."}],
        "github": [{"sha": "k3l4j5", "author": "dev", "message": "docs: update wiki", "date": "1 week ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 4: BAD CONFIG DEPLOYMENT (INSTANT CRASH)
    # ---------------------------------------------------------
    # Should Rollback (It is crashing, but restarting won't fix a hardcoded bad password)
    scenario_4 = {
        "metrics": {"cpu_utilization": "0%", "memory_usage_mb": 0, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "CrashLoopBackOff", "message": "Back-off restarting failed container", "timestamp": "Now"}],
        "logs": [{"timestamp": "Now", "message": "[FATAL] SQLException: Access Denied for user 'admin' (using password: NO)"}],
        "github": [{"sha": "p0q1w2", "author": "sre", "message": "chore: update database connection string environment variables", "date": "2 mins ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 5: ORGANIC CACHE BLOAT OOM (NO DEPLOYMENT)
    # ---------------------------------------------------------
    # Should Restart Pods (Very similar to Scenario 1, but missing the bad commit. A rollback makes no sense here as the code is months old. Restarting flushes the cache memory.)
    scenario_5 = {
        "metrics": {"cpu_utilization": "Stable", "memory_usage_mb": 4096, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "OOMKilling", "message": "Memory cgroup out of memory", "timestamp": "Now"}],
        "logs": [{"timestamp": "Now", "message": "[FATAL] OutOfMemoryError: Java heap space"}],
        "github": [{"sha": "z9x8c7", "author": "dev", "message": "feat: initial commit", "date": "4 months ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 6: COMPLETELY UNKNOWN ALIEN ERROR (NO RUNBOOK)
    # ---------------------------------------------------------
    # Should NOOP (Unknown external API failure). Restarting or scaling won't fix a third-party outage.
    scenario_6 = {
        "metrics": {"cpu_utilization": "5%", "memory_usage_mb": 100, "memory_limit_mb": 4096},
        "k8s_events": [],
        "logs": [{"timestamp": "Now", "message": "[ERROR] UnknownHostException: api.thirdparty-vendor.com Name or service not known"}],
        "github": [{"sha": "m3n4b5", "author": "dev", "message": "chore: linting", "date": "1 day ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 7: ZERO-SHOT COMMON ERROR (NO RUNBOOK)
    # ---------------------------------------------------------
    # Should Scale (Service is overwhelmed, but the agent has ZERO instructions on how to handle it. It must rely on its own LLM pre-training)
    scenario_7 = {
        "metrics": {"cpu_utilization": "99.9%", "memory_usage_mb": 500, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "FailedProbes", "message": "Liveness probe failed: HTTP timeout", "timestamp": "Now"}],
        "logs": [{"timestamp": "Now", "message": "[ERROR] ThreadPoolExecutor exhausted. Rejecting requests."}],
        "github": [{"sha": "x9y8z7", "author": "dev", "message": "fix: typo in readme", "date": "3 days ago"}]
    }

    print("STARTING BATCH EVALUATION...")
    print("Testing Amazon Nova's reasoning capabilities across diverse incident signatures.")
    
    run_test_scenario("Redis Bad Deployment Memory Leak", scenario_1, expected_tool="rollback_deployment")
    time.sleep(2) 
    run_test_scenario("Payment Service Traffic Surge", scenario_2, expected_tool="scale_deployment")
    time.sleep(2)
    run_test_scenario("Thread Deadlock Freeze", scenario_3, expected_tool="restart_pods")
    time.sleep(2)
    run_test_scenario("Bad DB Config Deployment Crash", scenario_4, expected_tool="rollback_deployment")
    time.sleep(2)
    run_test_scenario("Organic Cache Bloat OOM", scenario_5, expected_tool="restart_pods")
    time.sleep(2)
    run_test_scenario("Unknown Third-Party API Outage", scenario_6, expected_tool="noop_require_human")
    time.sleep(2)
    run_test_scenario("Zero-Shot Traffic Surge (No Runbook)", scenario_7, expected_tool="scale_deployment")

if __name__ == "__main__":
    main()

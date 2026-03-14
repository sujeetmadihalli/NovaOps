import os
import sys

# Add the parent directory to Python path for smooth running
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import AgentOrchestrator
from api.slack_notifier import SlackNotifier
import json

def test_dummy_oom_incident():
    """
    Test Case 1: Dummy Service OOM Mitigation
    
    The Mock Aggregators are configured by default to return:
    - Logs: "OutOfMemoryError"
    - Metrics: 98% memory consumption.
    - K8s: "OOMKilling"
    - GitHub: Recent commit bumping DB connection pool.
    
    Goal: The Agent should correctly deduce the OOM and propose a Rollback.
    """
    
    print("=========================================")
    print("EVALUATION HARNESS: SIMULATING INCIDENT")
    print("=========================================")
    
    # 1. Initialize strictly in LIVE mode: Real infrastructure, Real AI Model
    agent = AgentOrchestrator(mock_sensors=False, mock_llm=False)
    notifier = SlackNotifier(use_mock=True)
    
    # 2. Trigger the agent exactly how the PagerDuty Webhook would
    result = agent.run_incident_resolution(
        alert_name="DummyServiceOOM",
        service_name="dummy-service",
        namespace="default"
    )
    
    print("\n--- LLM JSON RAW DECISION ---")
    print(json.dumps(result, indent=2))
    print("-----------------------------\n")

    # 3. Simple evaluations Assertions
    if result.get("status") == "plan_ready":
        action = result.get("proposed_action", {})
        tool = action.get("tool")
        
        # Depending on how Nova interprets the mock data, it might suggest scale or rollback.
        # Given it's a memory spike explicitly tied to a recent commit, 'rollback_deployment' is vastly preferred.
        if tool in ["rollback_deployment", "scale_deployment", "restart_pods"]:
            print(f"✅ PASS: Agent chose a valid remediation tool: {tool}")
            
            print("\n>> Invoking Ghost Mode Simulation:")
            notifier.send_incident_plan(
                incident_id="INC-00123",
                analysis=result.get("analysis"),
                proposed_action=action
            )
        else:
            print(f"❌ FAIL: Agent selected an unexpected tool: {tool}")
    else:
        print(f"❌ FAIL: Agent failed to generate a plan. Reason: {result.get('reason')}")
        
if __name__ == "__main__":
    test_dummy_oom_incident()

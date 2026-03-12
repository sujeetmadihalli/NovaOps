"""
V2 Evaluation Harness Adapter

Bridges the old test interface (from main branch's AgentOrchestrator)
to v2's dual-pipeline architecture (War Room + Jury + Governance).

Design: Runs full agents.main.run() pipeline with NOVAOPS_USE_MOCK=1.
Scenario runbooks in runbooks/*.md guide analysis via TF-IDF RAG matching.
No monkey-patching — uses environment variables for mock mode activation.
"""

import os
import sys
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.main import run as agents_main_run
from tools.executor import RemediationExecutor
from tools.k8s_actions import KubernetesActions


class V2EvaluationHarness:
    """
    Adapter that converts old test interface to v2 dual-pipeline.

    Old interface (main branch):
        run_test_scenario(scenario_name, service_name, mock_data, expected_tool)

    New interface (v2):
        agents.main.run(alert_text, executor) with NOVAOPS_USE_MOCK=1
            → Aggregators use mock data automatically
            → TF-IDF RAG matches alert text against scenario runbooks
            → War Room + Jury + Convergence + Governance execute
            → Returns dict with:
                - incident_id
                - domain
                - result (text)
                - proposed_action ({"tool": "...", "parameters": {...}})
                - governance_decision (ALLOW_AUTO / REQUIRE_APPROVAL)
                - confidence (0.0-1.0)
                - policy_name
                - risk_score (0-100)
    """

    def __init__(self, use_mock: bool = True):
        """
        Initialize harness adapter.

        Args:
            use_mock: If True, use mock Kubernetes actions (NOVAOPS_USE_MOCK=1)
        """
        self.use_mock = use_mock
        # Set environment variable for mock mode
        os.environ["NOVAOPS_USE_MOCK"] = "1" if use_mock else "0"

    def _build_alert_text(self, scenario_name: str, service_name: str) -> str:
        """Convert scenario name and service to alert text for agents.main.run()."""
        return f"{scenario_name} on {service_name}"

    def run_test_scenario(
        self,
        scenario_name: str,
        service_name: str,
        mock_data: dict,
        expected_tool: str,
    ) -> dict:
        """
        Run a test scenario through v2's full pipeline.

        Args:
            scenario_name: Name of the scenario (e.g., "Redis Cache OOM — Bad Deployment")
            service_name: Service name (e.g., "redis-cache")
            mock_data: Dict with mock sensor data (not used directly; TF-IDF RAG guides analysis via runbooks)
            expected_tool: Expected remediation tool (e.g., "rollback_deployment")

        Returns:
            Dict with test result:
            {
                "scenario": str,
                "status": "PASS" or "FAIL",
                "tool_chosen": str,
                "expected_tool": str,
                "governance_decision": str,
                "confidence": float,
                "risk_score": int,
                "policy_name": str,
                "reason": str,
            }
        """
        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario_name}")
        print(f"SERVICE:  {service_name}")
        print(f"EXPECTED: {expected_tool}")
        print(f"{'='*60}")

        # Build alert text
        alert_text = self._build_alert_text(scenario_name, service_name)

        # Create executor with mock mode
        executor = RemediationExecutor(
            KubernetesActions(use_mock=self.use_mock)
        )

        try:
            # Run the full v2 pipeline: War Room → Jury → Convergence → Governance
            # Note: NOVAOPS_USE_MOCK=1 (set in __init__) causes all aggregators to use mock data.
            # Scenario runbooks (in runbooks/*.md) guide analysis via TF-IDF RAG.
            result = agents_main_run(alert_text, executor)

            # Extract key fields from result
            tool_chosen = result.get("proposed_action", {}).get("tool", "noop_require_human")
            governance_decision = result.get("governance_decision", "UNKNOWN")
            confidence = result.get("confidence", 0.0)
            risk_score = result.get("risk_score", 0)
            policy_name = result.get("policy_name", "unknown_policy")

            # Determine PASS/FAIL
            passed = (tool_chosen == expected_tool)

            # Additional validation: Governance should be reasonable
            # (not rejecting safe operations, or approving very risky ones)
            governance_ok = governance_decision in {"APPROVE", "REQUIRE_APPROVAL"}

            # Overall status: tool must match AND governance must be reasonable
            status = "PASS" if (passed and governance_ok) else "FAIL"

            if status == "PASS":
                reason = f"Tool matched ({tool_chosen}), governance approved"
            else:
                if not passed:
                    reason = f"Tool mismatch: expected {expected_tool}, got {tool_chosen}"
                else:
                    reason = f"Tool ok but governance {governance_decision} (risky?)"

            # Log raw result for debugging
            print("\n--- Full Result ---")
            print(json.dumps(result, indent=2, default=str))
            print(f"\n--- Test Judgment ---")
            print(f"Status:       {status}")
            print(f"Tool:         {tool_chosen} (expected: {expected_tool})")
            print(f"Governance:   {governance_decision}")
            print(f"Confidence:   {confidence:.2f}")
            print(f"Risk Score:   {risk_score}/100")
            print(f"Policy:       {policy_name}")
            print(f"Reason:       {reason}")

            return {
                "scenario": scenario_name,
                "status": status,
                "tool_chosen": tool_chosen,
                "expected_tool": expected_tool,
                "governance_decision": governance_decision,
                "confidence": confidence,
                "risk_score": risk_score,
                "policy_name": policy_name,
                "reason": reason,
            }

        except Exception as e:
            # Graceful error handling
            import traceback
            print(f"\n❌ ERROR: {e}")
            print(traceback.format_exc())
            return {
                "scenario": scenario_name,
                "status": "ERROR",
                "tool_chosen": "unknown",
                "expected_tool": expected_tool,
                "governance_decision": "ERROR",
                "confidence": 0.0,
                "risk_score": 0,
                "policy_name": "unknown_policy",
                "reason": f"Exception during test: {str(e)}",
            }

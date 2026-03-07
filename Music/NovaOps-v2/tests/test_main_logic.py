import unittest
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

from agents import artifacts, main
from governance import gate, audit_log, report
from agents.main import _extract_action_from_text
from agents.schemas import parse_remediation


class MainLogicTests(unittest.TestCase):
    def test_parse_remediation_prefers_tool_field(self):
        plan = parse_remediation('{"tool": "restart_pods", "parameters": {"service_name": "api"}}')
        self.assertEqual(plan.to_action_dict(), {"tool": "restart_pods", "parameters": {"service_name": "api"}})

    def test_extract_action_from_json_text(self):
        action = _extract_action_from_text(
            '{"action_taken":"scale_deployment","parameters":{"service_name":"checkout","target_replicas":4}}'
        )
        self.assertEqual(action["tool"], "scale_deployment")
        self.assertEqual(action["parameters"]["target_replicas"], 4)

    def test_extract_action_from_embedded_json_preserves_parameters(self):
        action = _extract_action_from_text(
            'Recommended action: {"action_taken":"rollback_deployment","parameters":{"service_name":"checkout"}}'
        )
        self.assertEqual(
            action,
            {"tool": "rollback_deployment", "parameters": {"service_name": "checkout"}},
        )

    def test_extract_action_defaults_to_noop_when_missing(self):
        action = _extract_action_from_text("no remediation proposed")
        self.assertEqual(action, {"tool": "noop_require_human", "parameters": {}})

    def test_parse_remediation_rejects_unknown_tool(self):
        plan = parse_remediation('{"action_taken": "delete_cluster", "parameters": {"service_name": "api"}}')
        self.assertEqual(plan.action_taken, "noop_require_human")


class MainRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path("tests/.tmp")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.base_dir / uuid.uuid4().hex
        self.original_plans_dir = artifacts.PLANS_DIR
        self.original_gate_dir = gate.PLANS_DIR
        self.original_audit_dir = audit_log.PLANS_DIR
        self.original_report_dir = report.PLANS_DIR
        artifacts.PLANS_DIR = self.temp_dir
        gate.PLANS_DIR = self.temp_dir
        audit_log.PLANS_DIR = self.temp_dir
        report.PLANS_DIR = self.temp_dir

    def tearDown(self):
        artifacts.PLANS_DIR = self.original_plans_dir
        gate.PLANS_DIR = self.original_gate_dir
        audit_log.PLANS_DIR = self.original_audit_dir
        report.PLANS_DIR = self.original_report_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_returns_safe_fallback_when_graph_execution_fails(self):
        def _failing_graph(_alert_text: str):
            raise RuntimeError("bedrock unavailable")

        with patch.object(main, "build_war_room", return_value=(_failing_graph, "traffic_surge")):
            result = main.run("P2 traffic surge alert on checkout-service", executor=MagicMock())

        self.assertEqual(result["proposed_action"]["tool"], "noop_require_human")
        self.assertEqual(result["governance_decision"], "REQUIRE_APPROVAL")
        self.assertEqual(result["governance_status"], "pending_approval")
        self.assertIn("Investigation failed during agent execution", result["result"])

        incident_dir = self.temp_dir / result["incident_id"]
        self.assertTrue((incident_dir / "report.md").exists())
        self.assertTrue((incident_dir / "trace.json").exists())
        self.assertTrue((incident_dir / "governance.json").exists())

    def test_run_completes_end_to_end_in_mock_mode(self):
        with patch.dict("os.environ", {"NOVAOPS_USE_MOCK": "1"}, clear=False):
            result = main.run("P2 traffic surge alert on checkout-service in prod causing elevated latency")

        self.assertEqual(result["domain"], "traffic_surge")
        self.assertEqual(result["proposed_action"]["tool"], "scale_deployment")
        self.assertIn(result["governance_status"], {"auto_executed", "pending_approval"})

        incident_dir = self.temp_dir / result["incident_id"]
        self.assertTrue((incident_dir / "report.md").exists())
        self.assertTrue((incident_dir / "governance.json").exists())
        self.assertTrue((incident_dir / "governance_report.md").exists())

    def test_run_unknown_alert_stays_human_gated(self):
        with patch.dict("os.environ", {"NOVAOPS_USE_MOCK": "1"}, clear=False):
            result = main.run("Intermittent anomaly observed on checkout-service with unclear symptoms")

        self.assertEqual(result["domain"], "unknown")
        self.assertEqual(result["proposed_action"]["tool"], "noop_require_human")
        self.assertEqual(result["governance_decision"], "REQUIRE_APPROVAL")
        self.assertEqual(result["governance_status"], "pending_approval")


if __name__ == "__main__":
    unittest.main()

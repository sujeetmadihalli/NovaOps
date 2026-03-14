import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

from governance import audit_log, gate
from governance.gate import GovernanceGate


def _war_room(severity="P3", critic_confidence=0.9):
    hypothesis = SimpleNamespace(
        rank=1,
        description="cpu saturation",
        confidence=0.8,
        recommended_action="scale_deployment",
    )
    root_cause = SimpleNamespace(top_hypothesis=hypothesis, confidence_overall=0.8)
    critic = SimpleNamespace(
        verdict="PASS",
        confidence=critic_confidence,
        feedback="sufficient evidence",
        action_approved=True,
    )
    triage = SimpleNamespace(
        domain="traffic_surge",
        severity=severity,
        service_name="checkout",
        namespace="prod",
    )
    return SimpleNamespace(triage=triage, root_cause=root_cause, critic=critic)


class GovernanceGateLogicTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path("tests/.tmp")
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.plans_dir = self.temp_root / f"governance-{uuid.uuid4().hex}"
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.executor = Mock()

    def tearDown(self):
        for path in sorted(self.plans_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        if self.plans_dir.exists():
            self.plans_dir.rmdir()

    def _incident_dir(self, incident_id: str) -> Path:
        path = self.plans_dir / incident_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_governance(self, incident_id: str, payload: dict) -> None:
        inv_dir = self._incident_dir(incident_id)
        (inv_dir / "governance.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_evaluate_normalizes_incident_for_auto_execution(self):
        incident_id = "inc-auto"
        self._incident_dir(incident_id)
        self.executor.execute.return_value = {"success": True, "tool": "scale_deployment"}
        incident = {
            "proposed_action": {
                "tool": "scale_deployment",
                "parameters": {
                    "service_name": "checkout",
                    "namespace": "prod",
                    "target_replicas": 4,
                },
            },
            "domain": "traffic_surge",
        }

        with patch.object(gate, "PLANS_DIR", self.plans_dir), patch.object(audit_log, "PLANS_DIR", self.plans_dir):
            result = GovernanceGate(self.executor).evaluate(incident_id, incident, _war_room())

        self.assertEqual(result.status, "auto_executed")
        self.executor.execute.assert_called_once_with(
            {
                "proposed_tool": "scale_deployment",
                "action_parameters": {
                    "service_name": "checkout",
                    "namespace": "prod",
                    "target_replicas": 4,
                },
                "service_name": "checkout",
            }
        )

    def test_evaluate_marks_failed_auto_execution(self):
        incident_id = "inc-fail"
        self._incident_dir(incident_id)
        self.executor.execute.return_value = {"success": False, "tool": "scale_deployment"}
        incident = {
            "proposed_action": {
                "tool": "scale_deployment",
                "parameters": {
                    "service_name": "checkout",
                    "namespace": "prod",
                    "target_replicas": 4,
                },
            },
            "domain": "traffic_surge",
        }

        with patch.object(gate, "PLANS_DIR", self.plans_dir), patch.object(audit_log, "PLANS_DIR", self.plans_dir):
            result = GovernanceGate(self.executor).evaluate(incident_id, incident, _war_room())

        self.assertEqual(result.status, "execution_failed")
        self.assertFalse(result.auto_executed)

    def test_evaluate_forces_approval_when_convergence_disagrees(self):
        incident_id = "inc-conv-disagree"
        self._incident_dir(incident_id)
        incident = {
            "proposed_action": {
                "tool": "scale_deployment",
                "parameters": {
                    "service_name": "checkout",
                    "namespace": "prod",
                    "target_replicas": 4,
                },
            },
            "domain": "traffic_surge",
            "convergence": {
                "agree": False,
                "jury_escalation_reasons": ["jurors disagree"],
                "adjusted_confidence": 0.95,
                "confidence_source": "convergence_disagreement",
            },
        }

        with patch.object(gate, "PLANS_DIR", self.plans_dir), patch.object(audit_log, "PLANS_DIR", self.plans_dir):
            result = GovernanceGate(self.executor).evaluate(incident_id, incident, _war_room())

        self.assertEqual(result.decision, "REQUIRE_APPROVAL")
        self.assertEqual(result.status, "pending_approval")
        self.assertEqual(result.policy_name, "convergence_guard_require_approval")
        self.executor.execute.assert_not_called()

    def test_evaluate_keeps_noop_human_gated(self):
        incident_id = "inc-noop"
        self._incident_dir(incident_id)
        incident = {
            "proposed_action": {
                "tool": "noop_require_human",
                "parameters": {},
            },
            "domain": "unknown",
        }

        with patch.object(gate, "PLANS_DIR", self.plans_dir), patch.object(audit_log, "PLANS_DIR", self.plans_dir):
            result = GovernanceGate(self.executor).evaluate(incident_id, incident, _war_room(severity="P2", critic_confidence=0.2))

        self.assertEqual(result.decision, "REQUIRE_APPROVAL")
        self.assertEqual(result.status, "pending_approval")
        self.assertFalse(result.auto_executed)
        self.executor.execute.assert_not_called()

    def test_approve_and_execute_blocks_missing_governance(self):
        incident_id = "inc-missing"
        self._incident_dir(incident_id)

        with patch.object(gate, "PLANS_DIR", self.plans_dir), patch.object(audit_log, "PLANS_DIR", self.plans_dir):
            with self.assertRaisesRegex(ValueError, "Governance decision not found"):
                GovernanceGate(self.executor).approve_and_execute(incident_id, {})

        self.executor.execute.assert_not_called()

    def test_approve_and_execute_blocks_denied_incident(self):
        incident_id = "inc-denied"
        self._write_governance(
            incident_id,
            {
                "decision": "DENY",
                "policy_name": "deny_policy",
                "risk_score": 90,
                "status": "denied",
                "action": "rollback_deployment",
            },
        )

        with patch.object(gate, "PLANS_DIR", self.plans_dir), patch.object(audit_log, "PLANS_DIR", self.plans_dir):
            with self.assertRaisesRegex(ValueError, "Governance denied execution"):
                GovernanceGate(self.executor).approve_and_execute(incident_id, {"proposed_tool": "rollback_deployment"})

        self.executor.execute.assert_not_called()

    def test_approve_and_execute_blocks_duplicate_execution(self):
        incident_id = "inc-dup"
        self._write_governance(
            incident_id,
            {
                "decision": "ALLOW_AUTO",
                "policy_name": "safe_auto",
                "risk_score": 20,
                "status": "auto_executed",
                "action": "restart_pods",
            },
        )

        with patch.object(gate, "PLANS_DIR", self.plans_dir), patch.object(audit_log, "PLANS_DIR", self.plans_dir):
            with self.assertRaisesRegex(ValueError, "already executed"):
                GovernanceGate(self.executor).approve_and_execute(incident_id, {"proposed_tool": "restart_pods"})

        self.executor.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

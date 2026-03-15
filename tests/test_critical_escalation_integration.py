"""Integration tests for the critical voice escalation path.

Tests the full flow from trigger_agent_loop through escalation policy,
voice summary, Connect caller, and Slack fallback.
"""

import os
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from api import server
from api.escalation_policy import EscalationPolicy
from api.connect_caller import ConnectCaller, CallResult
from api.slack_notifier import SlackNotifier


class TestCriticalEscalationIntegration(unittest.TestCase):
    """End-to-end integration: critical incident triggers voice escalation."""

    def setUp(self):
        self.temp_dir = Path("tests/.tmp_escalation")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Set up mock environment
        self.env_patcher = patch.dict(os.environ, {
            "NOVAOPS_USE_MOCK": "true",
            "NOVAOPS_VOICE_USE_MOCK": "true",
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "true",
            "CRITICAL_SEVERITY_LEVELS": "P1",
            "CRITICAL_RISK_SCORE_THRESHOLD": "85",
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_agent_result(self, severity="P1", risk_score=90, gov_status="pending_approval"):
        return {
            "incident_id": "int-test-001",
            "domain": "oom",
            "result": "Pod checkout-abc crashed due to OOM. Heap exceeded 95%.",
            "proposed_action": {"tool": "restart_pods", "parameters": {"namespace": "prod"}},
            "governance_decision": "REQUIRE_APPROVAL",
            "risk_score": risk_score,
            "severity": severity,
            "confidence": 0.82,
            "confidence_source": "convergence_agreement",
            "governance_status": gov_status,
            "report_path": str(self.temp_dir / "report.md"),
        }

    @patch("api.server.connect_caller")
    @patch("api.server.notifier")
    @patch("api.server.escalation_policy")
    def test_critical_incident_triggers_call_and_slack(self, mock_policy, mock_notifier, mock_caller):
        """A P1 incident with high risk should trigger both call and Slack critical."""
        from api.escalation_policy import EscalationResult

        mock_policy.evaluate.return_value = EscalationResult(
            is_critical=True,
            reasons=["severity P1 is in critical list", "risk score 90 >= threshold 85"],
            severity="P1",
            risk_score=90.0,
        )
        mock_caller.place_call.return_value = CallResult(success=True, contact_id="mock-c1")
        mock_notifier.send_critical_escalation.return_value = True

        result = self._make_agent_result()

        server._try_voice_escalation(
            result=result,
            service_name="checkout-service",
            alert_name="OOMKilled",
            gov_status="pending_approval",
            proposed_action=result["proposed_action"],
        )

        # Verify call was placed
        mock_caller.place_call.assert_called_once()
        call_kwargs = mock_caller.place_call.call_args
        self.assertEqual(call_kwargs[1]["incident_id"], "int-test-001")
        self.assertIn("restart pods", call_kwargs[1]["briefing_script"])

        # Verify Slack critical escalation was sent
        mock_notifier.send_critical_escalation.assert_called_once()
        slack_kwargs = mock_notifier.send_critical_escalation.call_args[1]
        self.assertEqual(slack_kwargs["incident_id"], "int-test-001")
        self.assertFalse(slack_kwargs["call_failed"])

    @patch("api.server.connect_caller")
    @patch("api.server.notifier")
    @patch("api.server.escalation_policy")
    def test_non_critical_incident_skips_escalation(self, mock_policy, mock_notifier, mock_caller):
        """A P3 incident with low risk should not trigger voice escalation."""
        from api.escalation_policy import EscalationResult

        mock_policy.evaluate.return_value = EscalationResult(
            is_critical=False, severity="P3", risk_score=30.0
        )

        result = self._make_agent_result(severity="P3", risk_score=30)

        server._try_voice_escalation(
            result=result,
            service_name="logging-service",
            alert_name="HighLatency",
            gov_status="plan_ready",
            proposed_action=result["proposed_action"],
        )

        mock_caller.place_call.assert_not_called()
        mock_notifier.send_critical_escalation.assert_not_called()

    @patch("api.server.connect_caller")
    @patch("api.server.notifier")
    @patch("api.server.escalation_policy")
    def test_call_failure_sends_slack_with_call_failed_flag(self, mock_policy, mock_notifier, mock_caller):
        """When the outbound call fails, Slack escalation should indicate call_failed=True."""
        from api.escalation_policy import EscalationResult

        mock_policy.evaluate.return_value = EscalationResult(
            is_critical=True,
            reasons=["severity P1 is in critical list"],
            severity="P1",
            risk_score=90.0,
        )
        mock_caller.place_call.return_value = CallResult(
            success=False, error="Connect timeout"
        )
        mock_notifier.send_critical_escalation.return_value = True

        result = self._make_agent_result()

        server._try_voice_escalation(
            result=result,
            service_name="checkout-service",
            alert_name="OOMKilled",
            gov_status="pending_approval",
            proposed_action=result["proposed_action"],
        )

        mock_notifier.send_critical_escalation.assert_called_once()
        slack_kwargs = mock_notifier.send_critical_escalation.call_args[1]
        self.assertTrue(slack_kwargs["call_failed"])

    @patch("api.server.connect_caller")
    @patch("api.server.notifier")
    @patch("api.server.escalation_policy")
    def test_auto_executed_skips_escalation(self, mock_policy, mock_notifier, mock_caller):
        """Auto-executed incidents don't need voice escalation."""
        from api.escalation_policy import EscalationResult

        mock_policy.evaluate.return_value = EscalationResult(
            is_critical=False, severity="P1", risk_score=90.0
        )

        result = self._make_agent_result(gov_status="auto_executed")

        server._try_voice_escalation(
            result=result,
            service_name="checkout-service",
            alert_name="OOMKilled",
            gov_status="auto_executed",
            proposed_action=result["proposed_action"],
        )

        mock_caller.place_call.assert_not_called()


class TestSlackCriticalEscalation(unittest.TestCase):
    """Test the Slack critical escalation message format."""

    def test_mock_critical_escalation_succeeds(self):
        notifier = SlackNotifier(use_mock=True)
        result = notifier.send_critical_escalation(
            incident_id="inc-001",
            service_name="api-gateway",
            severity="P1",
            domain="traffic_surge",
            analysis="Massive traffic spike causing 503s.",
            proposed_action={"tool": "scale_deployment", "parameters": {"target_replicas": 10}},
            escalation_reasons=["severity P1 is in critical list"],
            call_failed=True,
        )
        self.assertTrue(result)

    def test_critical_escalation_with_no_reasons(self):
        notifier = SlackNotifier(use_mock=True)
        result = notifier.send_critical_escalation(
            incident_id="inc-002",
            service_name="auth-service",
            severity="P1",
            domain="deadlock",
            analysis="Database connection pool exhausted.",
            proposed_action={"tool": "restart_pods", "parameters": {}},
        )
        self.assertTrue(result)


class TestEscalationPolicyIntegration(unittest.TestCase):
    """Test the escalation policy with realistic incident data."""

    def test_p1_high_risk_is_critical(self):
        with patch.dict(os.environ, {
            "CRITICAL_SEVERITY_LEVELS": "P1",
            "CRITICAL_RISK_SCORE_THRESHOLD": "85",
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "true",
        }):
            policy = EscalationPolicy()
            result = policy.evaluate(
                severity="P1", risk_score=90,
                governance_decision="REQUIRE_APPROVAL",
                governance_status="pending_approval",
            )
            self.assertTrue(result.is_critical)
            self.assertEqual(len(result.reasons), 2)

    def test_p2_moderate_risk_not_critical(self):
        with patch.dict(os.environ, {
            "CRITICAL_SEVERITY_LEVELS": "P1",
            "CRITICAL_RISK_SCORE_THRESHOLD": "85",
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "true",
        }):
            policy = EscalationPolicy()
            result = policy.evaluate(
                severity="P2", risk_score=60,
                governance_decision="REQUIRE_APPROVAL",
                governance_status="pending_approval",
            )
            self.assertFalse(result.is_critical)


if __name__ == "__main__":
    unittest.main()

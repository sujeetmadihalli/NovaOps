"""Comprehensive end-to-end test for voice escalation features.

Tests the full pipeline from incident data through escalation policy,
voice summary generation, Connect caller mock, Slack fallback, and
artifact persistence — without requiring AWS credentials.
"""

import os
import json
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from api.escalation_policy import EscalationPolicy, EscalationResult
from api.voice_summary import (
    build_briefing_script, build_system_prompt,
    MAX_SCRIPT_WORDS, _extract_first_sentence, _shorten_id,
)
from api.connect_caller import ConnectCaller, CallResult
from api.slack_notifier import SlackNotifier
from api import server


class TestVoiceE2E_CriticalP1Incident(unittest.TestCase):
    """Simulate a real P1 OOM incident flowing through the entire voice path."""

    def setUp(self):
        self.incident = {
            "incident_id": "e2e-p1-oom-001",
            "service_name": "checkout-service",
            "alert_name": "OOMKilled",
            "domain": "oom",
            "severity": "P1",
            "risk_score": 92,
            "result": (
                "Pod checkout-service-7b9f4d-xk2lp crashed with OOMKilled. "
                "Container heap usage reached 97% (1.94Gi / 2Gi limit). "
                "Memory leak detected in /api/v2/cart endpoint after deploy abc123. "
                "Recommended immediate restart with increased memory limit."
            ),
            "proposed_action": {
                "tool": "restart_pods",
                "parameters": {"namespace": "prod", "service_name": "checkout-service"},
            },
            "governance_decision": "REQUIRE_APPROVAL",
            "governance_status": "pending_approval",
            "confidence": 0.82,
            "confidence_source": "convergence_agreement",
            "report_path": "",
        }
        self.plans_dir = Path("tests/.tmp_e2e_plans")
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.plans_dir.exists():
            shutil.rmtree(self.plans_dir, ignore_errors=True)

    def test_01_escalation_policy_detects_critical(self):
        """Step 1: Policy identifies P1 + high risk as critical."""
        with patch.dict(os.environ, {
            "CRITICAL_SEVERITY_LEVELS": "P1",
            "CRITICAL_RISK_SCORE_THRESHOLD": "85",
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "true",
        }):
            policy = EscalationPolicy()
            result = policy.evaluate(
                severity=self.incident["severity"],
                risk_score=self.incident["risk_score"],
                governance_decision=self.incident["governance_decision"],
                governance_status=self.incident["governance_status"],
            )

        self.assertTrue(result.is_critical, "P1 + risk 92 should be critical")
        self.assertEqual(len(result.reasons), 2, "Both severity and risk should trigger")
        print(f"  PASS: Critical detected — {result.reasons}")

    def test_02_briefing_script_quality(self):
        """Step 2: Briefing script is concise, informative, and under word limit."""
        script = build_briefing_script(
            incident_id=self.incident["incident_id"],
            service_name=self.incident["service_name"],
            severity=self.incident["severity"],
            domain=self.incident["domain"],
            analysis=self.incident["result"],
            proposed_action=self.incident["proposed_action"],
        )

        words = script.split()
        self.assertLessEqual(len(words), MAX_SCRIPT_WORDS)
        self.assertIn("checkout-service", script)
        self.assertIn("P1", script)
        self.assertIn("restart pods", script)
        self.assertIn("approval", script.lower())
        # Should use shortened ID
        self.assertIn("e2e-p1-o", script)
        print(f"  PASS: Briefing ({len(words)} words): {script}")

    def test_03_system_prompt_completeness(self):
        """Step 3: System prompt has all fields Nova needs for conversation."""
        prompt = build_system_prompt(
            incident_id=self.incident["incident_id"],
            service_name=self.incident["service_name"],
            severity=self.incident["severity"],
            domain=self.incident["domain"],
            analysis=self.incident["result"],
            proposed_action=self.incident["proposed_action"],
            alert_name=self.incident["alert_name"],
        )

        required_fragments = [
            "e2e-p1-oom-001",       # incident ID
            "checkout-service",      # service
            "OOMKilled",             # alert
            "P1",                    # severity
            "oom",                   # domain
            "OOMKilled",             # from analysis
            "restart pods",          # action
            "[ACTION_APPROVED]",     # approval token
            "[ACTION_REJECTED]",     # rejection token
            "under 3 sentences",     # conversation rule
            "phone call",            # context
        ]

        for fragment in required_fragments:
            self.assertIn(fragment, prompt, f"Prompt missing: {fragment}")
        print(f"  PASS: System prompt complete ({len(prompt)} chars)")

    def test_04_mock_call_succeeds(self):
        """Step 4: Mock Connect call returns success with contact ID."""
        caller = ConnectCaller(use_mock=True)
        script = build_briefing_script(
            incident_id=self.incident["incident_id"],
            service_name=self.incident["service_name"],
            severity=self.incident["severity"],
            domain=self.incident["domain"],
            analysis=self.incident["result"],
            proposed_action=self.incident["proposed_action"],
        )
        prompt = build_system_prompt(
            incident_id=self.incident["incident_id"],
            service_name=self.incident["service_name"],
            severity=self.incident["severity"],
            domain=self.incident["domain"],
            analysis=self.incident["result"],
            proposed_action=self.incident["proposed_action"],
            alert_name=self.incident["alert_name"],
        )

        result = caller.place_call(
            incident_id=self.incident["incident_id"],
            briefing_script=script,
            system_prompt=prompt,
            severity=self.incident["severity"],
            service_name=self.incident["service_name"],
        )

        self.assertTrue(result.success)
        self.assertIn("mock-contact", result.contact_id)
        self.assertIsNone(result.error)
        print(f"  PASS: Mock call placed — contact_id={result.contact_id}")

    def test_05_slack_critical_escalation_format(self):
        """Step 5: Slack critical message is well-formed."""
        notifier = SlackNotifier(use_mock=True)
        result = notifier.send_critical_escalation(
            incident_id=self.incident["incident_id"],
            service_name=self.incident["service_name"],
            severity=self.incident["severity"],
            domain=self.incident["domain"],
            analysis=self.incident["result"][:500],
            proposed_action=self.incident["proposed_action"],
            escalation_reasons=["severity P1 is in critical list", "risk score 92 >= threshold 85"],
            call_failed=False,
        )
        self.assertTrue(result)
        print("  PASS: Slack critical escalation sent (mock)")

    def test_06_slack_fallback_on_call_failure(self):
        """Step 6: When call fails, Slack fallback fires with call_failed=True."""
        notifier = SlackNotifier(use_mock=True)
        result = notifier.send_critical_escalation(
            incident_id=self.incident["incident_id"],
            service_name=self.incident["service_name"],
            severity=self.incident["severity"],
            domain=self.incident["domain"],
            analysis=self.incident["result"][:500],
            proposed_action=self.incident["proposed_action"],
            escalation_reasons=["severity P1 is in critical list"],
            call_failed=True,
        )
        self.assertTrue(result)
        print("  PASS: Slack fallback sent with call_failed=True")

    @patch("api.server.connect_caller")
    @patch("api.server.notifier")
    @patch("api.server.escalation_policy")
    def test_07_full_server_integration(self, mock_policy, mock_notifier, mock_caller):
        """Step 7: _try_voice_escalation wires everything together correctly."""
        mock_policy.evaluate.return_value = EscalationResult(
            is_critical=True,
            reasons=["severity P1 is in critical list", "risk score 92 >= threshold 85"],
            severity="P1",
            risk_score=92.0,
        )
        mock_caller.place_call.return_value = CallResult(success=True, contact_id="mock-c1")
        mock_notifier.send_critical_escalation.return_value = True

        server._try_voice_escalation(
            result=self.incident,
            service_name=self.incident["service_name"],
            alert_name=self.incident["alert_name"],
            gov_status="pending_approval",
            proposed_action=self.incident["proposed_action"],
        )

        # Verify all components were called
        mock_policy.evaluate.assert_called_once()
        mock_caller.place_call.assert_called_once()
        mock_notifier.send_critical_escalation.assert_called_once()

        # Verify call args
        call_kwargs = mock_caller.place_call.call_args[1]
        self.assertEqual(call_kwargs["incident_id"], "e2e-p1-oom-001")
        self.assertIn("restart pods", call_kwargs["briefing_script"])
        self.assertIn("[ACTION_APPROVED]", call_kwargs["system_prompt"])

        slack_kwargs = mock_notifier.send_critical_escalation.call_args[1]
        self.assertFalse(slack_kwargs["call_failed"])
        self.assertEqual(len(slack_kwargs["escalation_reasons"]), 2)
        print("  PASS: Full server integration wired correctly")


class TestVoiceE2E_NonCriticalIncident(unittest.TestCase):
    """Verify that non-critical incidents skip voice escalation entirely."""

    def test_p3_low_risk_skips_everything(self):
        with patch.dict(os.environ, {
            "CRITICAL_SEVERITY_LEVELS": "P1",
            "CRITICAL_RISK_SCORE_THRESHOLD": "85",
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "true",
        }):
            policy = EscalationPolicy()
            result = policy.evaluate(severity="P3", risk_score=25.0)

        self.assertFalse(result.is_critical)
        print("  PASS: P3/low-risk correctly skipped")

    @patch("api.server.connect_caller")
    @patch("api.server.notifier")
    @patch("api.server.escalation_policy")
    def test_server_does_not_call_connect(self, mock_policy, mock_notifier, mock_caller):
        mock_policy.evaluate.return_value = EscalationResult(
            is_critical=False, severity="P3", risk_score=25.0
        )

        server._try_voice_escalation(
            result={"incident_id": "inc-p3", "severity": "P3", "risk_score": 25,
                     "domain": "config_drift", "result": "Minor config change.",
                     "governance_decision": "ALLOW_AUTO", "governance_status": "auto_executed"},
            service_name="logging-svc",
            alert_name="ConfigDrift",
            gov_status="auto_executed",
            proposed_action={"tool": "noop_require_human", "parameters": {}},
        )

        mock_caller.place_call.assert_not_called()
        mock_notifier.send_critical_escalation.assert_not_called()
        print("  PASS: Non-critical -> no Connect call, no Slack critical")


class TestVoiceE2E_CallFailureFallback(unittest.TestCase):
    """Verify graceful degradation when Connect call fails."""

    @patch("api.server.connect_caller")
    @patch("api.server.notifier")
    @patch("api.server.escalation_policy")
    def test_connect_failure_triggers_slack_fallback(self, mock_policy, mock_notifier, mock_caller):
        mock_policy.evaluate.return_value = EscalationResult(
            is_critical=True,
            reasons=["severity P1 is in critical list"],
            severity="P1",
            risk_score=90.0,
        )
        mock_caller.place_call.return_value = CallResult(
            success=False, error="Connect instance not found"
        )
        mock_notifier.send_critical_escalation.return_value = True

        server._try_voice_escalation(
            result={"incident_id": "inc-fail", "severity": "P1", "risk_score": 90,
                     "domain": "oom", "result": "OOM crash.", "governance_decision": "REQUIRE_APPROVAL",
                     "governance_status": "pending_approval"},
            service_name="api-gateway",
            alert_name="OOMKilled",
            gov_status="pending_approval",
            proposed_action={"tool": "restart_pods", "parameters": {}},
        )

        # Call was attempted
        mock_caller.place_call.assert_called_once()
        # Slack fallback fired with call_failed=True
        mock_notifier.send_critical_escalation.assert_called_once()
        slack_kwargs = mock_notifier.send_critical_escalation.call_args[1]
        self.assertTrue(slack_kwargs["call_failed"])
        print("  PASS: Connect failure -> Slack fallback with call_failed=True")


class TestVoiceE2E_LambdaConversation(unittest.TestCase):
    """Test the Lambda handler conversation flow end-to-end."""

    def _make_event(self, transcript="", session_attrs=None):
        return {
            "sessionState": {
                "sessionAttributes": session_attrs or {
                    "incident_id": "e2e-lambda-001",
                    "system_prompt": build_system_prompt(
                        incident_id="e2e-lambda-001",
                        service_name="payment-api",
                        severity="P1",
                        domain="traffic_surge",
                        analysis="503 errors from traffic spike.",
                        proposed_action={"tool": "scale_deployment", "parameters": {"target_replicas": 8}},
                        alert_name="HighErrorRate",
                    ),
                    "callback_url": "http://localhost:8082",
                },
                "intent": {"name": "VoiceEscalation", "state": "InProgress"},
            },
            "inputTranscript": transcript,
            "invocationSource": "FulfillmentCodeHook",
        }

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_initial_greeting(self, mock_bedrock):
        from lambda_handlers.nova_connect_handler import handler

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [
                {"text": "Hey, this is NovaOps. We've got a P1 traffic surge on payment-api. "
                         "The war room is recommending we scale to 8 replicas. Want me to go ahead?"}
            ]}}
        }
        mock_bedrock.return_value = mock_client

        result = handler(self._make_event(transcript=""), None)

        self.assertEqual(result["sessionState"]["dialogAction"]["type"], "ElicitIntent")
        self.assertIn("payment-api", result["messages"][0]["content"])
        print(f"  PASS: Initial greeting: {result['messages'][0]['content'][:80]}...")

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    @patch("lambda_handlers.nova_connect_handler._trigger_approval")
    def test_approval_flow(self, mock_approve, mock_bedrock):
        from lambda_handlers.nova_connect_handler import handler

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [
                {"text": "Got it, scaling payment-api to 8 replicas now. [ACTION_APPROVED]"}
            ]}}
        }
        mock_bedrock.return_value = mock_client

        result = handler(self._make_event(transcript="Yes, go ahead and scale it"), None)

        self.assertEqual(result["sessionState"]["dialogAction"]["type"], "Close")
        self.assertEqual(result["sessionState"]["intent"]["state"], "Fulfilled")
        mock_approve.assert_called_once_with("http://localhost:8082", "e2e-lambda-001")
        print(f"  PASS: Approval detected -> API callback triggered")

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_rejection_flow(self, mock_bedrock):
        from lambda_handlers.nova_connect_handler import handler

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [
                {"text": "Understood, I won't make any changes. [ACTION_REJECTED]"}
            ]}}
        }
        mock_bedrock.return_value = mock_client

        result = handler(self._make_event(transcript="No, don't do anything"), None)

        self.assertEqual(result["sessionState"]["dialogAction"]["type"], "Close")
        print("  PASS: Rejection detected -> conversation closed")

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_multi_turn_conversation(self, mock_bedrock):
        """Simulate asking for details before approving."""
        from lambda_handlers.nova_connect_handler import handler

        mock_client = MagicMock()
        # Turn 1: asking for details
        mock_client.converse.return_value = {
            "output": {"message": {"content": [
                {"text": "The payment-api is returning 503s due to a sudden traffic spike. "
                         "Current replicas can't handle the load."}
            ]}}
        }
        mock_bedrock.return_value = mock_client

        result1 = handler(self._make_event(transcript="What exactly is happening?"), None)

        self.assertEqual(result1["sessionState"]["dialogAction"]["type"], "ElicitIntent")
        # Conversation history should be saved
        history = json.loads(
            result1["sessionState"]["sessionAttributes"].get("conversation_history", "[]")
        )
        self.assertGreater(len(history), 0)
        print(f"  PASS: Multi-turn — history has {len(history)} messages after turn 1")


class TestVoiceE2E_EdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_empty_analysis(self):
        script = build_briefing_script(
            incident_id="edge-001", service_name="svc",
            severity="P1", domain="unknown", analysis="",
            proposed_action={"tool": "noop_require_human", "parameters": {}},
        )
        self.assertIn("investigation", script.lower())
        print(f"  PASS: Empty analysis handled: {script[:60]}...")

    def test_very_long_analysis(self):
        long_text = "Critical failure detected. " * 200
        script = build_briefing_script(
            incident_id="edge-002", service_name="big-svc",
            severity="P1", domain="cascading_failure",
            analysis=long_text,
            proposed_action={"tool": "rollback_deployment", "parameters": {}},
        )
        self.assertLessEqual(len(script.split()), MAX_SCRIPT_WORDS)
        print(f"  PASS: Long analysis truncated to {len(script.split())} words")

    def test_missing_proposed_action(self):
        script = build_briefing_script(
            incident_id="edge-003", service_name="orphan-svc",
            severity="P1", domain="deadlock", analysis="Deadlock detected.",
            proposed_action=None,
        )
        self.assertIn("unknown action", script)
        print(f"  PASS: Missing action handled gracefully")

    def test_risk_exactly_at_threshold(self):
        with patch.dict(os.environ, {
            "CRITICAL_SEVERITY_LEVELS": "P1",
            "CRITICAL_RISK_SCORE_THRESHOLD": "85",
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "true",
        }):
            policy = EscalationPolicy()
            result = policy.evaluate(severity="P3", risk_score=85.0)
        self.assertTrue(result.is_critical, "Score exactly at threshold should trigger")
        print("  PASS: Risk exactly at threshold (85) -> critical")

    def test_disabled_escalation_blocks_everything(self):
        with patch.dict(os.environ, {
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "false",
        }):
            policy = EscalationPolicy()
            result = policy.evaluate(severity="P1", risk_score=99.0)
        self.assertFalse(result.is_critical)
        print("  PASS: Master switch off -> no escalation even for P1/99 risk")

    def test_connect_missing_all_config(self):
        with patch.dict(os.environ, {
            "NOVAOPS_VOICE_USE_MOCK": "false",
            "CONNECT_INSTANCE_ID": "",
            "CONNECT_CONTACT_FLOW_ID": "",
            "CONNECT_SOURCE_PHONE": "",
            "ONCALL_PHONE_NUMBER": "",
        }, clear=False):
            caller = ConnectCaller(use_mock=False)
            result = caller.place_call("inc-x", "brief", "prompt")
        self.assertFalse(result.success)
        self.assertIn("CONNECT_INSTANCE_ID", result.error)
        print(f"  PASS: Missing config -> graceful error: {result.error[:60]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

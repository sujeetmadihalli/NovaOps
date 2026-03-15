"""Unit tests for api.escalation_policy."""

import os
import unittest
from unittest.mock import patch

from api.escalation_policy import EscalationPolicy, EscalationResult


class TestEscalationPolicy(unittest.TestCase):
    """Test severity + risk-based escalation classification."""

    def _make_policy(self, env_overrides=None):
        env = {
            "CRITICAL_SEVERITY_LEVELS": "P1",
            "CRITICAL_RISK_SCORE_THRESHOLD": "85",
            "NOVAOPS_VOICE_ESCALATION_ENABLED": "true",
        }
        if env_overrides:
            env.update(env_overrides)
        with patch.dict(os.environ, env, clear=False):
            return EscalationPolicy()

    # ── Critical triggers ──────────────────────────────────────────

    def test_p1_severity_is_critical(self):
        policy = self._make_policy()
        result = policy.evaluate(severity="P1", risk_score=90.0)
        self.assertTrue(result.is_critical)
        self.assertTrue(any("severity" in r for r in result.reasons))

    def test_high_risk_score_is_critical(self):
        policy = self._make_policy()
        result = policy.evaluate(severity="P3", risk_score=92.0)
        self.assertTrue(result.is_critical)
        self.assertTrue(any("risk score" in r for r in result.reasons))

    def test_both_severity_and_risk_gives_two_reasons(self):
        policy = self._make_policy()
        result = policy.evaluate(severity="P1", risk_score=95.0)
        self.assertTrue(result.is_critical)
        self.assertEqual(len(result.reasons), 2)

    # ── Non-critical ───────────────────────────────────────────────

    def test_p2_low_risk_not_critical(self):
        policy = self._make_policy()
        result = policy.evaluate(severity="P2", risk_score=40.0)
        self.assertFalse(result.is_critical)
        self.assertEqual(result.reasons, [])

    def test_p3_below_threshold_not_critical(self):
        policy = self._make_policy()
        result = policy.evaluate(severity="P3", risk_score=84.9)
        self.assertFalse(result.is_critical)

    # ── Auto-executed skip ─────────────────────────────────────────

    def test_auto_executed_skips_escalation(self):
        policy = self._make_policy()
        result = policy.evaluate(
            severity="P1", risk_score=95.0,
            governance_status="auto_executed"
        )
        self.assertFalse(result.is_critical)

    # ── Config variations ──────────────────────────────────────────

    def test_custom_severity_levels(self):
        policy = self._make_policy({"CRITICAL_SEVERITY_LEVELS": "P1,P2"})
        result = policy.evaluate(severity="P2", risk_score=10.0)
        self.assertTrue(result.is_critical)

    def test_custom_risk_threshold(self):
        policy = self._make_policy({"CRITICAL_RISK_SCORE_THRESHOLD": "50"})
        result = policy.evaluate(severity="P4", risk_score=55.0)
        self.assertTrue(result.is_critical)

    def test_disabled_master_switch(self):
        policy = self._make_policy({"NOVAOPS_VOICE_ESCALATION_ENABLED": "false"})
        result = policy.evaluate(severity="P1", risk_score=99.0)
        self.assertFalse(result.is_critical)

    def test_case_insensitive_severity(self):
        policy = self._make_policy()
        result = policy.evaluate(severity="p1", risk_score=50.0)
        self.assertTrue(result.is_critical)

    def test_invalid_risk_threshold_defaults(self):
        policy = self._make_policy({"CRITICAL_RISK_SCORE_THRESHOLD": "not_a_number"})
        self.assertEqual(policy.risk_threshold, 85.0)

    # ── Result fields ──────────────────────────────────────────────

    def test_result_carries_severity_and_score(self):
        policy = self._make_policy()
        result = policy.evaluate(severity="P1", risk_score=91.0)
        self.assertEqual(result.severity, "P1")
        self.assertEqual(result.risk_score, 91.0)


if __name__ == "__main__":
    unittest.main()

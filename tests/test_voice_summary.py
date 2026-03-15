"""Unit tests for api.voice_summary."""

import unittest

from api.voice_summary import (
    build_briefing_script,
    build_system_prompt,
    MAX_SCRIPT_WORDS,
    _extract_first_sentence,
    _shorten_id,
)


class TestBriefingScript(unittest.TestCase):
    """Test the short TTS briefing script builder."""

    def _default_kwargs(self, **overrides):
        base = dict(
            incident_id="abc12345-6789-0000-1111-222233334444",
            service_name="checkout-service",
            severity="P1",
            domain="oom",
            analysis="Out of memory on pod checkout-abc. Heap usage exceeded 95%.",
            proposed_action={"tool": "restart_pods", "parameters": {"namespace": "prod"}},
        )
        base.update(overrides)
        return base

    def test_script_under_word_limit(self):
        script = build_briefing_script(**self._default_kwargs())
        word_count = len(script.split())
        self.assertLessEqual(word_count, MAX_SCRIPT_WORDS)

    def test_script_contains_service_name(self):
        script = build_briefing_script(**self._default_kwargs())
        self.assertIn("checkout-service", script)

    def test_script_contains_severity(self):
        script = build_briefing_script(**self._default_kwargs())
        self.assertIn("P1", script)

    def test_script_contains_proposed_action(self):
        script = build_briefing_script(**self._default_kwargs())
        self.assertIn("restart pods", script)

    def test_script_mentions_approval(self):
        script = build_briefing_script(**self._default_kwargs())
        self.assertIn("approval", script.lower())

    def test_script_with_no_proposed_action(self):
        script = build_briefing_script(**self._default_kwargs(proposed_action=None))
        self.assertIn("unknown action", script)

    def test_script_truncates_long_analysis(self):
        long_analysis = "Word " * 200
        script = build_briefing_script(**self._default_kwargs(analysis=long_analysis))
        self.assertLessEqual(len(script.split()), MAX_SCRIPT_WORDS)

    def test_shortened_incident_id(self):
        script = build_briefing_script(**self._default_kwargs())
        # Should use shortened ID, not full UUID
        self.assertNotIn("abc12345-6789-0000-1111-222233334444", script)
        self.assertIn("abc12345", script)


class TestSystemPrompt(unittest.TestCase):
    """Test the Nova system prompt builder."""

    def _default_kwargs(self, **overrides):
        base = dict(
            incident_id="inc-001",
            service_name="payment-api",
            severity="P1",
            domain="traffic_surge",
            analysis="Sudden spike in requests causing 503 errors.",
            proposed_action={"tool": "scale_deployment", "parameters": {"target_replicas": 5}},
            alert_name="HighErrorRate",
        )
        base.update(overrides)
        return base

    def test_prompt_contains_incident_details(self):
        prompt = build_system_prompt(**self._default_kwargs())
        self.assertIn("inc-001", prompt)
        self.assertIn("payment-api", prompt)
        self.assertIn("P1", prompt)
        self.assertIn("traffic_surge", prompt)
        self.assertIn("HighErrorRate", prompt)

    def test_prompt_contains_approval_tokens(self):
        prompt = build_system_prompt(**self._default_kwargs())
        self.assertIn("[ACTION_APPROVED]", prompt)
        self.assertIn("[ACTION_REJECTED]", prompt)

    def test_prompt_contains_action_detail(self):
        prompt = build_system_prompt(**self._default_kwargs())
        self.assertIn("scale deployment", prompt)
        self.assertIn("target_replicas", prompt)

    def test_prompt_truncates_long_analysis(self):
        long_analysis = "x" * 2000
        prompt = build_system_prompt(**self._default_kwargs(analysis=long_analysis))
        # Analysis excerpt should be capped at 800 chars
        self.assertNotIn("x" * 801, prompt)

    def test_prompt_with_no_analysis(self):
        prompt = build_system_prompt(**self._default_kwargs(analysis=""))
        self.assertIn("No analysis available", prompt)

    def test_prompt_conversation_rules(self):
        prompt = build_system_prompt(**self._default_kwargs())
        self.assertIn("under 3 sentences", prompt)
        self.assertIn("phone call", prompt)


class TestHelpers(unittest.TestCase):

    def test_extract_first_sentence_with_period(self):
        result = _extract_first_sentence("Pod crashed. Memory exceeded. Restarting.")
        self.assertEqual(result, "Pod crashed.")

    def test_extract_first_sentence_no_boundary(self):
        text = "No period here just a long run on sentence " * 5
        result = _extract_first_sentence(text)
        self.assertTrue(result.endswith("..."))

    def test_extract_first_sentence_empty(self):
        result = _extract_first_sentence("")
        self.assertIn("investigation", result.lower())

    def test_shorten_id_uuid(self):
        self.assertEqual(_shorten_id("abc12345-6789-0000"), "abc12345")

    def test_shorten_id_short(self):
        self.assertEqual(_shorten_id("inc-001"), "inc-001")


if __name__ == "__main__":
    unittest.main()

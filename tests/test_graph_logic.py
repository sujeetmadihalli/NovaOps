import unittest

from agents import graph


class _MessageObject:
    def __init__(self, content):
        self.content = content


class _AgentResult:
    def __init__(self, message):
        self.message = message


class _NodeResult:
    def __init__(self, result):
        self.result = result


class _State:
    def __init__(self, critic_message, loops=0):
        self.results = {
            "critic": _NodeResult(_AgentResult(critic_message)),
        }
        self.invocation_state = {"reflection_loops": loops}


class GraphLogicTests(unittest.TestCase):
    def test_parse_verdict_prefers_explicit_pass(self):
        verdict = graph._parse_verdict('verdict PASS. no failures detected')
        self.assertEqual(verdict, "PASS")

    def test_parse_verdict_handles_json_payload(self):
        verdict = graph._parse_verdict('{"verdict":"FAIL","feedback":"missing evidence"}')
        self.assertEqual(verdict, "FAIL")

    def test_parse_verdict_returns_unknown_for_ambiguous_text(self):
        verdict = graph._parse_verdict("analysis completed without explicit verdict")
        self.assertEqual(verdict, "UNKNOWN")

    def test_get_critic_text_supports_object_message(self):
        state = _State(_MessageObject([{"text": '{"verdict":"PASS"}'}]))
        self.assertEqual(graph._get_critic_text(state), '{"verdict":"pass"}')

    def test_critic_failed_increments_loop_on_unknown(self):
        state = _State(_MessageObject([{"text": "unclear response"}]), loops=1)
        failed = graph._critic_failed(state)
        self.assertTrue(failed)
        self.assertEqual(state.invocation_state["reflection_loops"], 2)

    def test_critic_passed_forces_progress_after_max_loops(self):
        state = _State(_MessageObject([{"text": "unclear response"}]), loops=graph.MAX_REFLECTION_LOOPS)
        self.assertTrue(graph._critic_passed(state))


if __name__ == "__main__":
    unittest.main()

"""Unit tests for lambda_handlers.nova_connect_handler."""

import json
import unittest
from unittest.mock import patch, MagicMock

from lambda_handlers.nova_connect_handler import handler, _load_messages, _save_messages


class TestNovaConnectHandler(unittest.TestCase):
    """Test the Lex V2 fulfillment Lambda handler."""

    def _make_event(self, transcript="", session_attrs=None, intent="VoiceEscalation"):
        return {
            "sessionState": {
                "sessionAttributes": session_attrs or {
                    "incident_id": "inc-test-001",
                    "system_prompt": "You are Nova. Ask about the incident.",
                    "callback_url": "http://localhost:8082",
                },
                "intent": {"name": intent, "state": "InProgress"},
            },
            "inputTranscript": transcript,
            "invocationSource": "FulfillmentCodeHook",
        }

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_normal_conversation_turn(self, mock_get_bedrock):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "I see the checkout service is down. Want to approve restart?"}]
                }
            }
        }
        mock_get_bedrock.return_value = mock_client

        event = self._make_event(transcript="What's going on?")
        result = handler(event, None)

        self.assertEqual(result["messages"][0]["content"],
                         "I see the checkout service is down. Want to approve restart?")
        # Should not close — conversation continues
        self.assertEqual(result["sessionState"]["dialogAction"]["type"], "ElicitIntent")

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    @patch("lambda_handlers.nova_connect_handler._trigger_approval")
    def test_approval_detected(self, mock_approve, mock_get_bedrock):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Got it, approving now. [ACTION_APPROVED]"}]
                }
            }
        }
        mock_get_bedrock.return_value = mock_client

        event = self._make_event(transcript="Yes, go ahead")
        result = handler(event, None)

        mock_approve.assert_called_once_with("http://localhost:8082", "inc-test-001")
        # Should close the conversation
        self.assertEqual(result["sessionState"]["dialogAction"]["type"], "Close")
        self.assertEqual(result["sessionState"]["intent"]["state"], "Fulfilled")

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_rejection_detected(self, mock_get_bedrock):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Understood, aborting. [ACTION_REJECTED]"}]
                }
            }
        }
        mock_get_bedrock.return_value = mock_client

        event = self._make_event(transcript="No, reject it")
        result = handler(event, None)

        self.assertEqual(result["sessionState"]["dialogAction"]["type"], "Close")

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_bedrock_failure_returns_fallback(self, mock_get_bedrock):
        mock_client = MagicMock()
        mock_client.converse.side_effect = Exception("Bedrock timeout")
        mock_get_bedrock.return_value = mock_client

        event = self._make_event(transcript="Hello")
        result = handler(event, None)

        self.assertIn("trouble connecting", result["messages"][0]["content"])
        self.assertEqual(result["sessionState"]["dialogAction"]["type"], "Close")

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_first_turn_no_transcript(self, mock_get_bedrock):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Hi, this is NovaOps calling about an incident."}]
                }
            }
        }
        mock_get_bedrock.return_value = mock_client

        event = self._make_event(transcript="")
        result = handler(event, None)

        self.assertIn("NovaOps", result["messages"][0]["content"])

    @patch("lambda_handlers.nova_connect_handler.get_bedrock")
    def test_conversation_history_preserved(self, mock_get_bedrock):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "The restart should fix it."}]
                }
            }
        }
        mock_get_bedrock.return_value = mock_client

        # Simulate a second turn with existing history
        prior_messages = [
            {"role": "user", "content": [{"text": "Hello"}]},
            {"role": "assistant", "content": [{"text": "Hi, calling about incident."}]},
        ]
        session_attrs = {
            "incident_id": "inc-002",
            "system_prompt": "You are Nova.",
            "callback_url": "http://localhost:8082",
            "conversation_history": json.dumps(prior_messages),
        }

        event = self._make_event(transcript="Tell me more", session_attrs=session_attrs)
        result = handler(event, None)

        # Bedrock should receive the full history (2 prior + 1 new user message)
        call_args = mock_client.converse.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        # At minimum, should have the prior messages + new utterance
        self.assertGreaterEqual(len(call_args[1].get("messages", [])), 3)


class TestMessageHelpers(unittest.TestCase):

    def test_load_messages_empty(self):
        self.assertEqual(_load_messages({}), [])

    def test_load_messages_valid_json(self):
        msgs = [{"role": "user", "content": [{"text": "hi"}]}]
        result = _load_messages({"conversation_history": json.dumps(msgs)})
        self.assertEqual(result, msgs)

    def test_load_messages_invalid_json(self):
        result = _load_messages({"conversation_history": "not json"})
        self.assertEqual(result, [])

    def test_save_messages_trims_to_12(self):
        attrs = {}
        messages = [{"role": "user", "content": [{"text": f"msg-{i}"}]} for i in range(20)]
        _save_messages(attrs, messages)
        loaded = json.loads(attrs["conversation_history"])
        self.assertEqual(len(loaded), 12)


if __name__ == "__main__":
    unittest.main()

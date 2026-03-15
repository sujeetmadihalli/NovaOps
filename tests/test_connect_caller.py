"""Unit tests for api.connect_caller."""

import os
import unittest
from unittest.mock import patch, MagicMock

from api.connect_caller import ConnectCaller, CallResult


class TestConnectCallerMock(unittest.TestCase):
    """Test the mock call path."""

    def test_mock_call_succeeds(self):
        caller = ConnectCaller(use_mock=True)
        result = caller.place_call(
            incident_id="inc-001",
            briefing_script="Test briefing",
            system_prompt="Test prompt",
        )
        self.assertTrue(result.success)
        self.assertIn("mock-contact", result.contact_id)

    def test_mock_call_includes_incident_id(self):
        caller = ConnectCaller(use_mock=True)
        result = caller.place_call(
            incident_id="inc-042",
            briefing_script="Test",
            system_prompt="Test",
        )
        self.assertIn("inc-042", result.contact_id)


class TestConnectCallerReal(unittest.TestCase):
    """Test the real call path (with mocked boto3)."""

    def _make_caller(self, env_overrides=None):
        env = {
            "NOVAOPS_VOICE_USE_MOCK": "false",
            "CONNECT_INSTANCE_ID": "test-instance",
            "CONNECT_CONTACT_FLOW_ID": "test-flow",
            "CONNECT_SOURCE_PHONE": "+15551234567",
            "ONCALL_PHONE_NUMBER": "+15559876543",
        }
        if env_overrides:
            env.update(env_overrides)
        with patch.dict(os.environ, env, clear=False):
            return ConnectCaller(use_mock=False)

    @patch("api.connect_caller.boto3")
    def test_real_call_success(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.start_outbound_voice_contact.return_value = {
            "ContactId": "contact-abc-123"
        }
        mock_boto3.client.return_value = mock_client

        caller = self._make_caller()
        caller._client = mock_client

        result = caller.place_call(
            incident_id="inc-001",
            briefing_script="Alert briefing",
            system_prompt="System prompt",
            severity="P1",
            service_name="checkout",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.contact_id, "contact-abc-123")
        mock_client.start_outbound_voice_contact.assert_called_once()

        call_args = mock_client.start_outbound_voice_contact.call_args
        self.assertEqual(call_args[1]["DestinationPhoneNumber"], "+15559876543")
        self.assertEqual(call_args[1]["InstanceId"], "test-instance")
        self.assertIn("incident_id", call_args[1]["Attributes"])

    @patch("api.connect_caller.boto3")
    def test_real_call_api_failure(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.start_outbound_voice_contact.side_effect = Exception("Connect error")
        mock_boto3.client.return_value = mock_client

        caller = self._make_caller()
        caller._client = mock_client

        result = caller.place_call(
            incident_id="inc-002",
            briefing_script="Alert",
            system_prompt="Prompt",
        )

        self.assertFalse(result.success)
        self.assertIn("Connect error", result.error)

    def test_missing_config_returns_error(self):
        caller = self._make_caller({"CONNECT_INSTANCE_ID": ""})
        result = caller.place_call(
            incident_id="inc-003",
            briefing_script="Alert",
            system_prompt="Prompt",
        )
        self.assertFalse(result.success)
        self.assertIn("CONNECT_INSTANCE_ID", result.error)

    @patch("api.connect_caller.boto3")
    def test_attributes_include_callback_url(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.start_outbound_voice_contact.return_value = {"ContactId": "c1"}
        mock_boto3.client.return_value = mock_client

        caller = self._make_caller()
        caller._client = mock_client

        caller.place_call(
            incident_id="inc-004",
            briefing_script="Brief",
            system_prompt="Prompt",
        )

        call_args = mock_client.start_outbound_voice_contact.call_args
        attrs = call_args[1]["Attributes"]
        self.assertIn("callback_url", attrs)
        self.assertIn("briefing_script", attrs)


if __name__ == "__main__":
    unittest.main()

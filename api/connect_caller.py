"""Amazon Connect outbound call wrapper for critical incident voice escalation.

Places an outbound phone call via Amazon Connect, passing incident context
as Contact Flow attributes so the Contact Flow + Lex + Lambda can drive
a real-time Nova conversation with the on-call engineer.

Configuration via environment variables:
  CONNECT_INSTANCE_ID     — Amazon Connect instance ID
  CONNECT_CONTACT_FLOW_ID — Contact Flow ID for voice escalation
  CONNECT_SOURCE_PHONE    — Outbound caller ID (E.164, e.g. +15551234567)
  ONCALL_PHONE_NUMBER     — On-call engineer's phone (E.164)
  NOVAOPS_VOICE_USE_MOCK  — "true" to log instead of calling (default: "true")
  NOVAOPS_API_CALLBACK_URL — URL the Lambda uses to call back for approval
"""

import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

import boto3

logger = logging.getLogger(__name__)


@dataclass
class CallResult:
    """Outcome of an outbound call attempt."""
    success: bool
    contact_id: Optional[str] = None
    error: Optional[str] = None


class ConnectCaller:
    """Places outbound calls via Amazon Connect for critical escalation."""

    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock or os.environ.get(
            "NOVAOPS_VOICE_USE_MOCK", "true"
        ).strip().lower() in {"1", "true", "yes", "on"}

        self.instance_id = os.environ.get("CONNECT_INSTANCE_ID", "")
        self.contact_flow_id = os.environ.get("CONNECT_CONTACT_FLOW_ID", "")
        self.source_phone = os.environ.get("CONNECT_SOURCE_PHONE", "")
        self.oncall_phone = os.environ.get("ONCALL_PHONE_NUMBER", "")
        self.callback_url = os.environ.get("NOVAOPS_API_CALLBACK_URL", "http://localhost:8082")

        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "connect",
                region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            )
        return self._client

    def place_call(
        self,
        incident_id: str,
        briefing_script: str,
        system_prompt: str,
        severity: str = "",
        service_name: str = "",
    ) -> CallResult:
        """Place an outbound call to the on-call engineer.

        The incident context is passed as Contact Flow attributes so the
        Contact Flow can play the initial briefing via Polly TTS, then
        hand off to a Lex bot backed by a Lambda that uses Nova for
        real-time conversation.

        Args:
            incident_id: The incident being escalated.
            briefing_script: Short TTS script for the initial greeting.
            system_prompt: Full Nova system prompt for the Lambda handler.
            severity: Incident severity level.
            service_name: Affected service name.

        Returns:
            CallResult with success flag and contact_id or error.
        """
        attributes = {
            "incident_id": incident_id,
            "briefing_script": briefing_script,
            "severity": severity,
            "service_name": service_name,
            "callback_url": self.callback_url,
            # System prompt is stored in a truncated form as a contact attribute.
            # The Lambda retrieves full context via the incident API if needed.
            "system_prompt_preview": system_prompt[:1024],
        }

        if self.use_mock:
            return self._mock_call(incident_id, attributes)

        return self._real_call(incident_id, attributes)

    def _mock_call(self, incident_id: str, attributes: Dict[str, str]) -> CallResult:
        """Log the call instead of actually dialing."""
        logger.info(
            f"[MOCK CALL] Would dial {self.oncall_phone or '+1XXXXXXXXXX'} "
            f"for incident {incident_id}"
        )
        logger.info(f"[MOCK CALL] Briefing: {attributes.get('briefing_script', '')}")
        logger.info(f"[MOCK CALL] Contact attributes: {json.dumps(attributes, indent=2)}")
        return CallResult(success=True, contact_id=f"mock-contact-{incident_id}")

    def _real_call(self, incident_id: str, attributes: Dict[str, str]) -> CallResult:
        """Place the actual outbound call via Amazon Connect."""
        if not all([self.instance_id, self.contact_flow_id,
                    self.source_phone, self.oncall_phone]):
            missing = []
            if not self.instance_id:
                missing.append("CONNECT_INSTANCE_ID")
            if not self.contact_flow_id:
                missing.append("CONNECT_CONTACT_FLOW_ID")
            if not self.source_phone:
                missing.append("CONNECT_SOURCE_PHONE")
            if not self.oncall_phone:
                missing.append("ONCALL_PHONE_NUMBER")
            error = f"Missing Connect config: {', '.join(missing)}"
            logger.error(f"Cannot place call: {error}")
            return CallResult(success=False, error=error)

        try:
            response = self.client.start_outbound_voice_contact(
                DestinationPhoneNumber=self.oncall_phone,
                ContactFlowId=self.contact_flow_id,
                InstanceId=self.instance_id,
                SourcePhoneNumber=self.source_phone,
                Attributes=attributes,
            )
            contact_id = response.get("ContactId", "unknown")
            logger.info(
                f"Outbound call placed: contact_id={contact_id} "
                f"destination={self.oncall_phone} incident={incident_id}"
            )
            return CallResult(success=True, contact_id=contact_id)

        except Exception as e:
            logger.error(f"Failed to place outbound call for {incident_id}: {e}")
            return CallResult(success=False, error=str(e))

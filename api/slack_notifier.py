"""Ghost Mode — Slack notification with approval buttons.

Supports two notification paths:
  1. send_incident_plan()      — standard incident notification (existing)
  2. send_critical_escalation() — high-visibility fallback for critical incidents
     when the outbound voice call fails or is unavailable
"""

import os
import json
import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class SlackNotifier:
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        self.webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    def send_incident_plan(self, incident_id: str, domain: str,
                           analysis: str, proposed_action: dict) -> bool:
        message_blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"NovaOps Alert: {incident_id}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Domain:* {domain}\n\n*Root Cause Analysis:*\n{analysis[:1500]}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Proposed Action:*\n```\n{json.dumps(proposed_action, indent=2)}\n```"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "action_id": "approve_incident",
                        "style": "primary",
                        "value": f"approve_{incident_id}"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "action_id": "reject_incident",
                        "style": "danger",
                        "value": f"reject_{incident_id}"
                    }
                ]
            }
        ]

        if self.use_mock or not self.webhook_url:
            logger.info(f"[Ghost Mode] Slack notification for {incident_id} (mock)")
            return True

        try:
            response = requests.post(
                self.webhook_url,
                json={"blocks": message_blocks, "text": f"NovaOps: {incident_id}"},
                timeout=10,
            )
            response.raise_for_status()
            logger.info("Slack notification sent.")
            return True
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return False

    def send_critical_escalation(
        self,
        incident_id: str,
        service_name: str,
        severity: str,
        domain: str,
        analysis: str,
        proposed_action: dict,
        escalation_reasons: Optional[List[str]] = None,
        call_failed: bool = False,
    ) -> bool:
        """Send a high-visibility critical escalation message to Slack.

        Used as a fallback when the outbound voice call fails or as a
        supplement to the phone call for visibility.

        Args:
            incident_id: Incident identifier.
            service_name: Affected service.
            severity: Incident severity (P1, etc.).
            domain: Incident domain classification.
            analysis: Root cause analysis text.
            proposed_action: Proposed remediation action dict.
            escalation_reasons: Why this was classified as critical.
            call_failed: Whether the outbound call attempt failed.
        """
        reason_text = ""
        if escalation_reasons:
            reason_text = "\n".join(f"  - {r}" for r in escalation_reasons)

        call_status = (
            "PHONE CALL FAILED — requires immediate Slack attention"
            if call_failed
            else "Phone call placed to on-call engineer"
        )

        message_blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"CRITICAL ESCALATION: {incident_id}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":rotating_light: *Severity:* {severity} | "
                        f"*Service:* {service_name} | *Domain:* {domain}\n\n"
                        f"*Call Status:* {call_status}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Root Cause Analysis:*\n{analysis[:1500]}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Proposed Action:*\n```\n{json.dumps(proposed_action, indent=2)}\n```",
                },
            },
        ]

        if reason_text:
            message_blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Escalation Reasons:*\n{reason_text}",
                },
            })

        message_blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "action_id": "approve_incident",
                    "style": "primary",
                    "value": f"approve_{incident_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject_incident",
                    "style": "danger",
                    "value": f"reject_{incident_id}",
                },
            ],
        })

        if self.use_mock or not self.webhook_url:
            logger.info(
                f"[Ghost Mode] CRITICAL escalation for {incident_id} "
                f"(mock, call_failed={call_failed})"
            )
            return True

        try:
            response = requests.post(
                self.webhook_url,
                json={
                    "blocks": message_blocks,
                    "text": f"CRITICAL ESCALATION: {incident_id} — {severity} on {service_name}",
                },
                timeout=10,
            )
            response.raise_for_status()
            logger.info(f"Critical Slack escalation sent for {incident_id}")
            return True
        except Exception as e:
            logger.error(f"Critical Slack escalation failed for {incident_id}: {e}")
            return False

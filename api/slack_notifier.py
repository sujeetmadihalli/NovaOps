"""Ghost Mode — Slack notification with approval buttons."""

import os
import json
import logging
import requests
from typing import Dict, Any

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
                        "style": "primary",
                        "value": f"approve_{incident_id}"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
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

import requests
import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SlackNotifier:
    """
    Implements the 'Ghost Mode' human-in-the-loop mechanism.
    Instead of executing immediately, the agent posts its findings and an 'Approve' button.
    """
    def __init__(self, use_mock: bool = False):
        self.use_mock = use_mock
        self.webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
        
    def send_incident_plan(self, incident_id: str, analysis: str, proposed_action: dict) -> bool:
        """
        Sends the Agent's reasoned plan to a Slack channel with an interactive button.
        """
        message_blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 Autonomous Agent Diagnosis: {incident_id}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Root Cause Analysis:*\n{analysis}"
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
                        "text": {
                            "type": "plain_text",
                            "text": "Approve Exec Plan",
                            "emoji": True
                        },
                        "style": "primary",
                        "value": "execute_plan"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Reject",
                            "emoji": True
                        },
                        "style": "danger",
                        "value": "reject_plan"
                    }
                ]
            }
        ]
        
        if self.use_mock or not self.webhook_url:
            logger.info("Mock Slack Message Generated:")
            # We print the raw blocks to stdout for debugging the evaluation harness
            print(json.dumps(message_blocks, indent=2))
            return True
            
        try:
            response = requests.post(
                self.webhook_url, 
                json={"blocks": message_blocks, "text": "New Incident Plan Ready"}
            )
            response.raise_for_status()
            logger.info("Slack notification sent successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

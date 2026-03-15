import boto3
from dotenv import load_dotenv
import json
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)


class NovaClient:
    """
    Wrapper for Amazon Bedrock to interact with Amazon Nova models.
    Used by the Jury Agent system for independent LLM deliberation.
    """
    def __init__(self, region: str | None = None, model_id: str | None = None, use_mock: bool = False):
        load_dotenv()

        self.model_id = (model_id or os.environ.get("NOVA_MODEL_ID") or "us.amazon.nova-2-lite-v1:0").strip()
        self.use_mock = use_mock

        resolved_region = (region or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1").strip()

        try:
            self.client = boto3.client('bedrock-runtime', region_name=resolved_region)
        except Exception as e:
            logger.warning(f"Could not initialize Bedrock client: {e}")
            self.use_mock = True

    def invoke(self, system_prompt: str, context_payload: str, max_tokens: int = 1000) -> Dict[str, Any]:
        if self.use_mock:
            return self._mock_invocation()

        try:
            body = json.dumps({
                "schemaVersion": "messages-v1",
                "messages": [
                    {"role": "user", "content": [{"text": context_payload}]}
                ],
                "system": [{"text": system_prompt}],
                "inferenceConfig": {
                    "maxTokens": max_tokens,
                    "temperature": 0.1,
                    "topP": 0.9
                }
            })

            response = self.client.invoke_model(
                body=body,
                modelId=self.model_id,
                accept='application/json',
                contentType='application/json'
            )

            response_body = json.loads(response.get('body').read())
            return {
                "success": True,
                "content": response_body.get('output', {}).get('message', {}).get('content', [{'text': ''}])[0].get('text', '')
            }
        except Exception as e:
            logger.error(f"Failed to invoke Nova: {e}")
            return {"success": False, "error": str(e)}

    def _mock_invocation(self) -> Dict[str, Any]:
        mock_response = {
            "root_cause_analysis": "Mock: OOM after recent deployment. Rollback recommended.",
            "action": {
                "tool": "rollback_deployment",
                "parameters": {"service_name": "payment-service"}
            }
        }
        return {
            "success": True,
            "content": json.dumps(mock_response)
        }

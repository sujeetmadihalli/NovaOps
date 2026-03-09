import boto3
from dotenv import load_dotenv
import json
import logging
import os
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class NovaClient:
    """
    Wrapper for Amazon Bedrock to interact with Amazon Nova models.
    Leveraging the massive 300K context window for incident resolution.
    """
    def __init__(self, region: str = "us-east-1", model_id: str = "amazon.nova-pro-v1:0", use_mock: bool = False):
        self.model_id = model_id
        self.use_mock = use_mock
        self.region = region
        self.client = None
        
        # Load the newly created .env file automatically
        load_dotenv()
        
    def _get_client(self):
        if not self.client and not self.use_mock:
            try:
                self.client = boto3.client('bedrock-runtime', region_name=self.region)
            except Exception as e:
                logger.warning(f"Could not initialize Bedrock client: {e}")
                self.use_mock = True
        return self.client
            
    def invoke(self, system_prompt: str, context_payload: str, max_tokens: int = 1000) -> Dict[str, Any]:
        """
        Sends the massive context payload to Nova and expecting a JSON tool-call or resolution plan.
        """
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
                    "temperature": 0.1,  # Low temp for analytical tasks
                    "topP": 0.9
                }
            })
            
            client = self._get_client()
            if self.use_mock: # In case the lazy-load failed
                return self._mock_invocation()
                
            response = client.invoke_model(
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
        """
        Returns a mocked JSON tool call response for local testing/Ghost mode simulation.
        """
        mock_response = {
            "root_cause_analysis": "The logs indicate an OutOfMemoryError in consecutive crashes. The Prometheus metrics confirm memory spiked to 100% just after a deployment was rolled out 15 minutes ago. The runbook suggests a rollback.",
            "action": {
                "tool": "rollback_deployment",
                "parameters": {"service_name": "redis-cache"}
            }
        }
        return {
            "success": True,
            "content": json.dumps(mock_response)
        }

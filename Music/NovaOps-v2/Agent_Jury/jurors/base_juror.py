import json
import logging
import re
from typing import Dict, Any

from agent.nova_client import NovaClient

logger = logging.getLogger(__name__)

VALID_TOOLS = ["rollback_deployment", "scale_deployment", "restart_pods", "query_more_logs", "noop_require_human"]


class BaseJuror:
    """
    Base class for all jury members.
    Each juror is a specialised LLM that analyses the incident from its own lens
    and returns a structured verdict with a confidence score.

    Jurors receive ONLY raw incident context — not the War Room's reasoning.
    This preserves full independence and prevents groupthink.
    """
    name: str = "BaseJuror"
    specialisation: str = ""

    def __init__(self, use_mock: bool = False):
        self.llm = NovaClient(use_mock=use_mock)

    def _get_system_prompt(self) -> str:
        raise NotImplementedError

    def _build_context(self, incident_context: Dict[str, Any]) -> str:
        raise NotImplementedError

    def _mock_deliberate(self) -> Dict[str, Any]:
        return {
            "juror": self.name,
            "verdict": f"{self.name} mock verdict: inconclusive.",
            "confidence": 0.5,
            "recommended_action": "noop_require_human",
            "reasoning": "Mock mode — no real LLM call made."
        }

    def deliberate(self, incident_context: Dict[str, Any]) -> Dict[str, Any]:
        if self.llm.use_mock:
            verdict = self._mock_deliberate()
            verdict["juror"] = self.name
            return verdict

        system_prompt = self._get_system_prompt()
        context = self._build_context(incident_context)

        response = self.llm.invoke(system_prompt, context, max_tokens=800)

        if not response["success"]:
            logger.error(f"[{self.name}] LLM call failed: {response.get('error')}")
            return self._failure_verdict(f"LLM invocation failed: {response.get('error')}")

        raw = response["content"]

        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{.*\})', raw, re.DOTALL)

        if not json_match:
            logger.warning(f"[{self.name}] No JSON block found in response")
            return self._failure_verdict("No valid JSON found in LLM response")

        try:
            verdict = json.loads(json_match.group(1))
            verdict["juror"] = self.name
            verdict["confidence"] = max(0.0, min(1.0, float(verdict.get("confidence", 0.0))))

            if verdict.get("recommended_action") not in VALID_TOOLS:
                logger.warning(f"[{self.name}] Invalid tool '{verdict.get('recommended_action')}' — defaulting to noop_require_human")
                verdict["recommended_action"] = "noop_require_human"

            return verdict

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[{self.name}] JSON parse error: {e}")
            return self._failure_verdict(f"JSON parse error: {e}")

    def _failure_verdict(self, reason: str) -> Dict[str, Any]:
        return {
            "juror": self.name,
            "verdict": f"{self.name} could not reach a verdict.",
            "confidence": 0.0,
            "recommended_action": "noop_require_human",
            "reasoning": reason
        }

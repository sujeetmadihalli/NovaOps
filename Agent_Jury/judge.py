import json
import logging
import re
from typing import Dict, Any, List

from agent.nova_client import NovaClient

logger = logging.getLogger(__name__)

VALID_TOOLS = ["rollback_deployment", "scale_deployment", "restart_pods", "query_more_logs", "noop_require_human"]

SYSTEM_PROMPT = """
You are the Chief Judge of an AI Incident Resolution Jury.
You have received independent verdicts from 4 specialist jurors, each analysing a different dimension of the incident.

Your responsibilities:
1. Weigh each juror's verdict against their confidence score
2. Identify where jurors agree (strong signal) and where they disagree (uncertainty)
3. Synthesise a single definitive root cause explanation
4. Select the single best remediation action from the valid tool list
5. Assign an overall confidence score to your final verdict

A juror with confidence 0.0 failed to produce a verdict — discount their opinion heavily.
When jurors disagree, favour the highest-confidence verdict unless another juror provides compelling counter-evidence.
If the Anomaly Specialist detected external/unknown categories, escalate via noop_require_human unless you have overwhelming evidence from other jurors.

Valid remediation tools:
- rollback_deployment (bad code/config change)
- scale_deployment (load / resource exhaustion)
- restart_pods (deadlock / cache bloat)
- query_more_logs (insufficient evidence)
- noop_require_human (unknown, complex, or unsafe to automate)

Respond STRICTLY as a JSON block wrapped in ```json ... ```:
```json
{
    "final_root_cause": "Definitive explanation of root cause based on all juror evidence",
    "judge_reasoning": "How you weighed the juror opinions and resolved any disagreements",
    "proposed_action": {
        "tool": "tool_name_here",
        "parameters": {}
    },
    "confidence": 0.0,
    "dissenting_jurors": ["list juror names that disagreed significantly with the final verdict"]
}
```
"""


class Judge:
    """
    The Judge LLM synthesises all 4 juror verdicts into a final binding verdict.
    Runs after all jurors have deliberated in parallel.
    """

    def __init__(self, use_mock: bool = False):
        self.llm = NovaClient(use_mock=use_mock)

    def deliberate(self, alert_name: str, service_name: str, juror_verdicts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Takes all juror verdicts and renders a final binding verdict.
        """
        if self.llm.use_mock:
            # Pick the highest-confidence juror action as the mock judge's decision
            best = max(juror_verdicts, key=lambda v: v.get("confidence", 0.0), default={})
            return {
                "final_root_cause": best.get("verdict", "Mock judge verdict: deferred to highest-confidence juror."),
                "judge_reasoning": f"Mock mode — selected verdict from {best.get('juror', 'unknown')} with confidence {best.get('confidence', 0.0):.2f}.",
                "proposed_action": {"tool": best.get("recommended_action", "noop_require_human"), "parameters": {}},
                "confidence": best.get("confidence", 0.5),
                "dissenting_jurors": []
            }

        context = self._build_context(alert_name, service_name, juror_verdicts)
        response = self.llm.invoke(SYSTEM_PROMPT, context, max_tokens=1000)

        if not response["success"]:
            logger.error(f"[Judge] LLM call failed: {response.get('error')}")
            return self._failure_verdict(f"Judge LLM failed: {response.get('error')}")

        raw = response["content"]

        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{.*\})', raw, re.DOTALL)

        if not json_match:
            logger.warning("[Judge] No JSON block found in response")
            return self._failure_verdict("Judge produced no valid JSON verdict")

        try:
            verdict = json.loads(json_match.group(1))
            verdict["confidence"] = max(0.0, min(1.0, float(verdict.get("confidence", 0.0))))

            action = verdict.get("proposed_action", {})
            if action.get("tool") not in VALID_TOOLS:
                logger.warning(f"[Judge] Invalid tool '{action.get('tool')}' — defaulting to noop_require_human")
                verdict["proposed_action"] = {"tool": "noop_require_human", "parameters": {}}

            return verdict

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[Judge] JSON parse error: {e}")
            return self._failure_verdict(f"Judge JSON parse error: {e}")

    def _build_context(self, alert_name: str, service_name: str, juror_verdicts: List[Dict[str, Any]]) -> str:
        verdicts_text = ""
        for v in juror_verdicts:
            verdicts_text += f"""
--- {v.get('juror', 'Unknown Juror')} (Confidence: {v.get('confidence', 0.0):.2f}) ---
Verdict: {v.get('verdict', 'N/A')}
Recommended Action: {v.get('recommended_action', 'N/A')}
Reasoning: {v.get('reasoning', 'N/A')}
Detected Anomaly Categories: {v.get('detected_categories', [])}
"""

        return f"""
--- INCIDENT UNDER REVIEW ---
Alert: {alert_name}
Service: {service_name}

--- JUROR VERDICTS ---
{verdicts_text}

Based on all juror verdicts above, render your final binding verdict.
"""

    def _failure_verdict(self, reason: str) -> Dict[str, Any]:
        return {
            "final_root_cause": "Judge failed to render a verdict.",
            "judge_reasoning": reason,
            "proposed_action": {"tool": "noop_require_human", "parameters": {}},
            "confidence": 0.0,
            "dissenting_jurors": []
        }

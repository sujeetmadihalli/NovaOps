import json
import logging
from typing import Dict, Any

from Agent_Jury.jurors.base_juror import BaseJuror

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a Senior SRE Log Analyst serving on an incident jury.
Your ONLY job is to analyse error logs and crash traces to determine root cause.
You are not responsible for infrastructure, deployments, or external dependencies — focus exclusively on what the logs tell you.

Look for:
- Exception types, stack traces, and error messages
- OOM (OutOfMemoryError) signals
- Repeated crash patterns or error loops
- Log timestamps that indicate when failures began

Respond STRICTLY as a JSON block wrapped in ```json ... ```:
```json
{
    "verdict": "One clear sentence explaining what the logs indicate as root cause",
    "confidence": 0.0,
    "recommended_action": "one of: rollback_deployment | scale_deployment | restart_pods | query_more_logs | noop_require_human",
    "reasoning": "Step-by-step reasoning from the log evidence"
}
```
Confidence: 1.0 = certain, 0.0 = no signal in logs. Be honest — if logs are inconclusive, say so with low confidence.
"""


class LogAnalystJuror(BaseJuror):
    name = "Log Analyst"
    specialisation = "Error logs, crash traces, exception patterns, OOM signals"

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _build_context(self, incident_context: Dict[str, Any]) -> str:
        return f"""
--- INCIDENT ALERT ---
Name: {incident_context.get('alert_name')}
Service: {incident_context.get('service_name')}

--- YOUR EVIDENCE: ERROR LOGS ---
{json.dumps(incident_context.get('logs', []), indent=2)}

Analyse only the logs above. What do they tell you about the root cause?
"""

    def _mock_deliberate(self) -> Dict[str, Any]:
        return {
            "juror": self.name,
            "verdict": "Logs show repeated OutOfMemoryError crashes immediately following the latest deployment.",
            "confidence": 0.88,
            "recommended_action": "rollback_deployment",
            "reasoning": "Fatal OOM errors appear in 3 consecutive log lines. Pattern started 15 mins after deploy."
        }

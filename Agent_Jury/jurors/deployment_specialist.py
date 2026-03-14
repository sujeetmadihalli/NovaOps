import json
import logging
from typing import Dict, Any

from Agent_Jury.jurors.base_juror import BaseJuror

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a Senior SRE Deployment & Code Change Specialist serving on an incident jury.
Your ONLY job is to analyse recent Git commits, deployments, and runbook history to determine root cause.
You are not responsible for live logs or infrastructure metrics — focus exclusively on what changed in the codebase or config recently.

Look for:
- Commits deployed within 30 minutes before the incident
- Config changes (env vars, resource limits, feature flags)
- Dependency version bumps that could introduce regressions
- Rollout timing correlated with the incident start time
- Runbook guidance that matches this alert pattern

Respond STRICTLY as a JSON block wrapped in ```json ... ```:
```json
{
    "verdict": "One clear sentence explaining what the deployment history indicates as root cause",
    "confidence": 0.0,
    "recommended_action": "one of: rollback_deployment | scale_deployment | restart_pods | query_more_logs | noop_require_human",
    "reasoning": "Step-by-step reasoning from the commit and runbook evidence"
}
```
Confidence: 1.0 = certain, 0.0 = no deployment signal. If no recent commits exist, state low confidence.
"""


class DeploymentSpecialistJuror(BaseJuror):
    name = "Deployment Specialist"
    specialisation = "Git commits, deployment timing, config regressions, runbook matching"

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _build_context(self, incident_context: Dict[str, Any]) -> str:
        return f"""
--- INCIDENT ALERT ---
Name: {incident_context.get('alert_name')}
Service: {incident_context.get('service_name')}

--- YOUR EVIDENCE: RECENT COMMITS ---
{json.dumps(incident_context.get('commits', []), indent=2)}

--- YOUR EVIDENCE: RUNBOOK ---
{incident_context.get('runbook', 'No runbook found.')}

Analyse only the commits and runbook above. What do they tell you about the root cause?
"""

    def _mock_deliberate(self) -> Dict[str, Any]:
        return {
            "juror": self.name,
            "verdict": "A memory-intensive caching commit was deployed 15 minutes before the incident.",
            "confidence": 0.85,
            "recommended_action": "rollback_deployment",
            "reasoning": "Commit increasing redis cache TTL deployed at 14:17 UTC. Incident began at 14:32 UTC. Runbook recommends rollback when correlated with recent deployment."
        }

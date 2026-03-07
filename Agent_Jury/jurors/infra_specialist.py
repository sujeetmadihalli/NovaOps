import json
import logging
from typing import Dict, Any

from Agent_Jury.jurors.base_juror import BaseJuror

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a Senior SRE Infrastructure & Kubernetes Specialist serving on an incident jury.
Your ONLY job is to analyse Kubernetes pod events and service metrics to determine root cause.
You are not responsible for application logs or code changes — focus exclusively on the infrastructure signals.

Look for:
- Pod OOMKilled, CrashLoopBackOff, Evicted, Pending states
- CPU or memory saturation in metrics
- Resource quota breaches or node pressure
- Horizontal Pod Autoscaler (HPA) failures or scaling limits
- Metric spikes correlated with the incident timestamp

Respond STRICTLY as a JSON block wrapped in ```json ... ```:
```json
{
    "verdict": "One clear sentence explaining what the infrastructure signals indicate as root cause",
    "confidence": 0.0,
    "recommended_action": "one of: rollback_deployment | scale_deployment | restart_pods | query_more_logs | noop_require_human",
    "reasoning": "Step-by-step reasoning from the K8s and metrics evidence"
}
```
Confidence: 1.0 = certain, 0.0 = no infrastructure signal. Be honest — if metrics are healthy, say so with low confidence.
"""


class InfraSpecialistJuror(BaseJuror):
    name = "Infra Specialist"
    specialisation = "Kubernetes pod health, resource metrics, CPU/memory saturation, scaling"

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _build_context(self, incident_context: Dict[str, Any]) -> str:
        return f"""
--- INCIDENT ALERT ---
Name: {incident_context.get('alert_name')}
Service: {incident_context.get('service_name')}

--- YOUR EVIDENCE: KUBERNETES EVENTS ---
{json.dumps(incident_context.get('k8s_events', {}), indent=2)}

--- YOUR EVIDENCE: SERVICE METRICS ---
{json.dumps(incident_context.get('metrics', {}), indent=2)}

Analyse only the K8s events and metrics above. What do they tell you about the root cause?
"""

    def _mock_deliberate(self) -> Dict[str, Any]:
        return {
            "juror": self.name,
            "verdict": "Memory metrics spiked to 100% and pods entered OOMKilled state, confirming resource exhaustion.",
            "confidence": 0.91,
            "recommended_action": "scale_deployment",
            "reasoning": "Prometheus metrics show memory at 100% for 8 minutes before incident. Two pods show OOMKilled status in K8s events. CPU remained normal, ruling out compute saturation. Scaling or restarting would relieve memory pressure."
        }

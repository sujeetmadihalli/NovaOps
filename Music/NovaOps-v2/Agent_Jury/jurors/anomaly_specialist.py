import json
import logging
import re
from typing import Dict, Any, List, Tuple

from Agent_Jury.jurors.base_juror import BaseJuror

logger = logging.getLogger(__name__)

# Pattern signatures for categories the other 3 jurors are NOT specialised in
ANOMALY_SIGNATURES: List[Tuple[str, List[str], str]] = [
    (
        "External API / Third-Party Outage",
        [
            r"connection refused", r"upstream connect error", r"502 bad gateway",
            r"503 service unavailable", r"third.?party", r"webhook failed",
            r"ECONNREFUSED", r"ECONNRESET", r"upstream.*timeout"
        ],
        "noop_require_human"
    ),
    (
        "Network / DNS Failure",
        [
            r"DNS resolution failed", r"no such host", r"network unreachable",
            r"i/o timeout", r"dial tcp.*refused", r"getaddrinfo",
            r"UnknownHostException"
        ],
        "noop_require_human"
    ),
    (
        "Database / Data Layer Issue",
        [
            r"deadlock", r"connection pool exhausted", r"too many connections",
            r"slow query", r"ORA-\d+", r"pg_", r"mysql.*error",
            r"redis.*timeout", r"ENOTFOUND.*db", r"relation.*does not exist"
        ],
        "noop_require_human"
    ),
    (
        "Security / Auth Failure",
        [
            r"401 unauthorized", r"403 forbidden", r"JWT.*invalid",
            r"token.*expired", r"signature.*verification.*failed",
            r"auth.*failed", r"invalid.*credentials", r"SSL.*handshake"
        ],
        "noop_require_human"
    ),
]

SYSTEM_PROMPT = """
You are a Senior SRE Anomaly & Unknown Incident Specialist serving on an incident jury.
Your role is to catch what the other specialists (Log Analyst, Infra Specialist, Deployment Specialist) might miss.

Focus on:
- External dependency failures (third-party APIs, payment gateways, CDNs)
- Network and DNS failures
- Database deadlocks, connection pool exhaustion, slow queries
- Security and authentication failures
- Novel patterns not matching any known runbook

You will also receive a pre-analysis of pattern matches found in the raw context.
Use that as your primary signal combined with your own reasoning.

Respond STRICTLY as a JSON block wrapped in ```json ... ```:
```json
{
    "verdict": "One clear sentence on what anomalous or unknown factor is causing this incident",
    "confidence": 0.0,
    "recommended_action": "one of: rollback_deployment | scale_deployment | restart_pods | query_more_logs | noop_require_human",
    "reasoning": "Step-by-step reasoning. If no anomaly detected, state clearly that the incident fits known categories.",
    "detected_categories": []
}
```
Confidence: 1.0 = certain anomaly, 0.0 = nothing anomalous detected.
If you find nothing in your domain, output low confidence — that is a valid and useful verdict.
"""


class AnomalySpecialistJuror(BaseJuror):
    name = "Anomaly Specialist"
    specialisation = "External APIs, network failures, database issues, security events, unknown patterns"

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _pattern_scan(self, incident_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_text = json.dumps(incident_context, default=str).lower()
        matched = []
        for category, patterns, action in ANOMALY_SIGNATURES:
            hits = [p for p in patterns if re.search(p, raw_text, re.IGNORECASE)]
            if hits:
                matched.append({"category": category, "matched_patterns": hits, "recommended_action": action})
                logger.info(f"[{self.name}] Pattern match: '{category}' — patterns: {hits}")
        return matched

    def _rag_confidence_signal(self, incident_context: Dict[str, Any]) -> str:
        runbook = incident_context.get("runbook", "")
        if not runbook.strip() or "no runbook" in runbook.lower() or "no relevant" in runbook.lower():
            return "LOW — No runbook matched this incident. High probability of novel/unknown incident type."
        return "OK — A runbook exists for this alert. May fall within known categories."

    def _build_context(self, incident_context: Dict[str, Any]) -> str:
        pattern_hits = self._pattern_scan(incident_context)
        rag_signal = self._rag_confidence_signal(incident_context)
        return f"""
--- INCIDENT ALERT ---
Name: {incident_context.get('alert_name')}
Service: {incident_context.get('service_name')}

--- LAYER 1: RAG CONFIDENCE SIGNAL ---
{rag_signal}

--- LAYER 2: ANOMALY PATTERN SCAN RESULTS ---
{json.dumps(pattern_hits, indent=2) if pattern_hits else "No anomaly patterns matched in the raw context."}

--- FULL RAW CONTEXT (for your residual analysis) ---
Logs: {json.dumps(incident_context.get('logs', []), indent=2)}
Metrics: {json.dumps(incident_context.get('metrics', {}), indent=2)}
K8s Events: {json.dumps(incident_context.get('k8s_events', {}), indent=2)}
Commits: {json.dumps(incident_context.get('commits', []), indent=2)}

Based on the pattern scan and RAG signal above, what anomalous or unknown factor — if any — is driving this incident?
If nothing in your domain is present, clearly state that with low confidence.
"""

    def deliberate(self, incident_context: Dict[str, Any]) -> Dict[str, Any]:
        if self.llm.use_mock:
            return self._mock_deliberate()
        pattern_hits = self._pattern_scan(incident_context)
        verdict = super().deliberate(incident_context)

        if pattern_hits and verdict.get("confidence", 0.0) < 0.5:
            logger.info(f"[{self.name}] Pattern scan found {len(pattern_hits)} match(es) — boosting confidence")
            verdict["confidence"] = max(verdict["confidence"], 0.6)
            verdict["detected_categories"] = [h["category"] for h in pattern_hits]

        if "detected_categories" not in verdict:
            verdict["detected_categories"] = [h["category"] for h in pattern_hits]

        return verdict

    def _mock_deliberate(self) -> Dict[str, Any]:
        return {
            "juror": self.name,
            "verdict": "No external or anomalous factors detected. Incident appears within known categories.",
            "confidence": 0.1,
            "recommended_action": "noop_require_human",
            "reasoning": "Pattern scan found no external API, network, database, or security signatures.",
            "detected_categories": []
        }

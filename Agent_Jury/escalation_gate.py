import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

JUROR_CONFIDENCE_THRESHOLD = 0.4
JUDGE_CONFIDENCE_THRESHOLD = 0.6
JUROR_DISAGREEMENT_THRESHOLD = 0.4


class EscalationGate:
    """
    6-check safety gate between the jury verdict and any action.
    In the hybrid pipeline, escalation results feed into the Convergence Check,
    which adjusts the confidence score passed to v2's GovernanceGate.
    """

    def evaluate(
        self,
        judge_verdict: Dict[str, Any],
        juror_verdicts: List[Dict[str, Any]],
        agent_status: str = "plan_ready"
    ) -> Dict[str, Any]:
        reasons = []

        # Check 1: Jury pipeline failed
        if agent_status == "failed":
            reasons.append("Jury pipeline failed to produce a valid verdict — cannot auto-proceed.")

        # Check 2: Judge confidence too low
        judge_confidence = judge_verdict.get("confidence", 0.0)
        if judge_confidence < JUDGE_CONFIDENCE_THRESHOLD:
            reasons.append(
                f"Judge confidence {judge_confidence:.2f} is below threshold {JUDGE_CONFIDENCE_THRESHOLD}."
            )

        # Check 3: Any juror had zero confidence (LLM failure)
        failed_jurors = [v["juror"] for v in juror_verdicts if v.get("confidence", 0.0) == 0.0]
        if failed_jurors:
            reasons.append(f"Jurors failed to deliberate: {failed_jurors}.")

        # Check 4: High-confidence jurors disagree on action
        actions = [v.get("recommended_action") for v in juror_verdicts if v.get("confidence", 0.0) >= JUROR_CONFIDENCE_THRESHOLD]
        if len(set(actions)) > 1:
            reasons.append(f"Jurors disagree on remediation: {set(actions)}.")

        # Check 5: Anomaly Specialist detected external/unknown categories
        anomaly_juror = next((v for v in juror_verdicts if v.get("juror") == "Anomaly Specialist"), None)
        if anomaly_juror:
            detected = anomaly_juror.get("detected_categories", [])
            if detected:
                reasons.append(f"Anomaly Specialist detected: {detected}.")

        # Check 6: Judge chose noop_require_human
        proposed_tool = judge_verdict.get("proposed_action", {}).get("tool", "")
        if proposed_tool == "noop_require_human":
            reasons.append("Judge determined this incident requires human intervention.")

        should_escalate = len(reasons) > 0

        if should_escalate:
            logger.warning(f"[EscalationGate] ESCALATING. Reasons: {reasons}")
        else:
            logger.info(f"[EscalationGate] Cleared all checks. Safe to proceed with: {proposed_tool}")

        return {
            "should_escalate": should_escalate,
            "reasons": reasons,
            "safe_to_proceed": not should_escalate
        }

    def build_escalation_summary(
        self,
        incident_id: str,
        alert_name: str,
        service_name: str,
        judge_verdict: Dict[str, Any],
        juror_verdicts: List[Dict[str, Any]],
        gate_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        juror_summary = "\n".join([
            f"  • {v['juror']} (conf: {v.get('confidence', 0.0):.2f}): {v.get('verdict', 'N/A')}"
            for v in juror_verdicts
        ])
        return {
            "incident_id": incident_id,
            "alert_name": alert_name,
            "service_name": service_name,
            "escalation_reasons": gate_result["reasons"],
            "judge_root_cause": judge_verdict.get("final_root_cause", "Unknown"),
            "judge_confidence": judge_verdict.get("confidence", 0.0),
            "juror_summary": juror_summary,
            "proposed_action": judge_verdict.get("proposed_action", {}),
            "message": (
                "Jury escalated this incident for human review.\n\n"
                f"Reasons:\n" + "\n".join(f"  - {r}" for r in gate_result["reasons"])
            )
        }

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Thresholds
JUROR_CONFIDENCE_THRESHOLD = 0.4   # Juror below this is considered unreliable
JUDGE_CONFIDENCE_THRESHOLD = 0.6   # Judge below this means the jury is uncertain
JUROR_DISAGREEMENT_THRESHOLD = 0.4 # Max confidence spread between top jurors before flagging disagreement


class EscalationGate:
    """
    Sits between the jury verdict and any action execution.
    Ensures that every low-confidence, unknown, or failed incident
    is routed to human review instead of being silently dropped or auto-executed.

    This fixes the silent failure bug in server.py where status='failed'
    was only logged and never escalated.
    """

    def evaluate(
        self,
        judge_verdict: Dict[str, Any],
        juror_verdicts: List[Dict[str, Any]],
        agent_status: str = "plan_ready"
    ) -> Dict[str, Any]:
        """
        Evaluates whether the jury's verdict can proceed or must be escalated to a human.

        Returns a gate result:
        {
            "should_escalate": bool,
            "reasons": [list of escalation reasons],
            "safe_to_proceed": bool
        }
        """
        reasons = []

        # Check 1: Agent/Jury pipeline itself failed
        if agent_status == "failed":
            reasons.append("Jury pipeline failed to produce a valid verdict — cannot auto-proceed.")

        # Check 2: Judge confidence too low
        judge_confidence = judge_verdict.get("confidence", 0.0)
        if judge_confidence < JUDGE_CONFIDENCE_THRESHOLD:
            reasons.append(
                f"Judge confidence {judge_confidence:.2f} is below threshold {JUDGE_CONFIDENCE_THRESHOLD} — verdict is uncertain."
            )

        # Check 3: Any individual juror had zero confidence (LLM failure)
        failed_jurors = [v["juror"] for v in juror_verdicts if v.get("confidence", 0.0) == 0.0]
        if failed_jurors:
            reasons.append(f"Jurors failed to deliberate: {failed_jurors}. Incomplete jury panel.")

        # Check 4: Juror disagreement — top jurors recommend different actions
        actions = [v.get("recommended_action") for v in juror_verdicts if v.get("confidence", 0.0) >= JUROR_CONFIDENCE_THRESHOLD]
        if len(set(actions)) > 1:
            reasons.append(
                f"Jurors disagree on remediation action: {set(actions)}. Human arbitration needed."
            )

        # Check 5: Anomaly Specialist detected an unknown/external category
        anomaly_juror = next((v for v in juror_verdicts if v.get("juror") == "Anomaly Specialist"), None)
        if anomaly_juror:
            detected = anomaly_juror.get("detected_categories", [])
            if detected:
                reasons.append(
                    f"Anomaly Specialist detected non-standard incident categories: {detected}. Escalating for human review."
                )

        # Check 6: Judge itself chose noop_require_human
        proposed_tool = judge_verdict.get("proposed_action", {}).get("tool", "")
        if proposed_tool == "noop_require_human":
            reasons.append("Judge determined this incident requires human intervention (noop_require_human selected).")

        should_escalate = len(reasons) > 0

        if should_escalate:
            logger.warning(f"[EscalationGate] ESCALATING to human review. Reasons: {reasons}")
        else:
            logger.info(f"[EscalationGate] Verdict cleared all checks. Safe to proceed with action: {proposed_tool}")

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
        """
        Builds a structured human-readable escalation payload for Slack/alerting.
        """
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
                "The Jury Agent has escalated this incident for human review.\n"
                "The jury could not reach a high-confidence automated verdict.\n\n"
                f"Escalation reasons:\n" +
                "\n".join(f"  - {r}" for r in gate_result["reasons"])
            )
        }

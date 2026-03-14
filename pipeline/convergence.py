"""
Convergence Check — compares War Room verdict vs Jury verdict.

The Jury runs on raw incident context with no knowledge of the War Room's reasoning.
This module compares the two independent conclusions:

  AGREE   → confidence is boosted before passing to GovernanceGate
            (two independent pipelines reaching the same conclusion is strong signal)

  DISAGREE → confidence is penalised before passing to GovernanceGate
             (disagreement means uncertainty — human review is warranted)
             GovernanceGate will hit REQUIRE_APPROVAL regardless of policy.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

AGREEMENT_BOOST = 0.15       # Added to base confidence when both agree
DISAGREEMENT_PENALTY = 0.30  # Subtracted from base confidence when they disagree
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0


def check_convergence(
    war_room_action: Dict[str, Any],
    jury_result: Dict[str, Any],
    war_room,
) -> Dict[str, Any]:
    """
    Compare War Room proposed action vs Jury proposed action.

    Args:
        war_room_action: proposed_action dict from agents/main.py {"tool": ..., "parameters": ...}
        jury_result:     full return value from JuryOrchestrator.run()
        war_room:        WarRoomResult object from persist_graph_artifacts()

    Returns a convergence dict consumed by GovernanceGate._build_context():
    {
        "agree": bool,
        "war_room_action": str,
        "jury_action": str,
        "war_room_confidence": float,
        "jury_confidence": float,
        "adjusted_confidence": float,
        "confidence_source": str,   # "convergence_agreement" | "convergence_disagreement"
        "summary": str,
        "jury_escalation_reasons": list,
        "jury_judge_reasoning": str,
    }
    """
    war_action = (war_room_action or {}).get("tool", "noop_require_human")
    jury_action = (jury_result.get("proposed_action") or {}).get("tool", "noop_require_human")
    jury_confidence = jury_result.get("confidence", 0.0)
    jury_should_escalate = jury_result.get("should_escalate", False)

    base_confidence = _extract_war_room_confidence(war_room)

    # Agreement: same tool AND jury did not flag escalation
    agree = (war_action == jury_action) and not jury_should_escalate

    if agree:
        adjusted = min(MAX_CONFIDENCE, base_confidence + AGREEMENT_BOOST)
        source = "convergence_agreement"
        summary = (
            f"War Room and Jury independently recommend '{war_action}'. "
            f"Agreement boosts confidence {base_confidence:.2f} → {adjusted:.2f}."
        )
        logger.info(f"[Convergence] AGREE on '{war_action}'. Confidence {base_confidence:.2f} → {adjusted:.2f}")
    else:
        adjusted = max(MIN_CONFIDENCE, base_confidence - DISAGREEMENT_PENALTY)
        source = "convergence_disagreement"
        jury_reasons = jury_result.get("escalation_reasons", [])
        summary = (
            f"DISAGREEMENT: War Room recommends '{war_action}', "
            f"Jury recommends '{jury_action}'. "
            f"Confidence {base_confidence:.2f} → {adjusted:.2f}. Human review required. "
            f"Jury escalation reasons: {jury_reasons}"
        )
        logger.warning(
            f"[Convergence] DISAGREE — War Room='{war_action}' Jury='{jury_action}'. "
            f"Confidence {base_confidence:.2f} → {adjusted:.2f}"
        )

    return {
        "agree": agree,
        "war_room_action": war_action,
        "jury_action": jury_action,
        "war_room_confidence": base_confidence,
        "jury_confidence": jury_confidence,
        "adjusted_confidence": adjusted,
        "confidence_source": source,
        "summary": summary,
        "jury_escalation_reasons": jury_result.get("escalation_reasons", []),
        "jury_judge_reasoning": (jury_result.get("judge_verdict") or {}).get("judge_reasoning", ""),
        "jury_juror_verdicts": jury_result.get("juror_verdicts", []),
    }


def _extract_war_room_confidence(war_room) -> float:
    """Extract best available confidence from WarRoomResult, in priority order."""
    if war_room is None:
        return 0.5

    # Critic is the final quality gate — most reliable confidence signal
    if hasattr(war_room, "critic") and war_room.critic:
        c = getattr(war_room.critic, "confidence", None)
        if c is not None:
            try:
                return float(c)
            except (TypeError, ValueError):
                pass

    # Root cause top hypothesis
    if hasattr(war_room, "root_cause") and war_room.root_cause:
        h = getattr(war_room.root_cause, "top_hypothesis", None)
        if h and hasattr(h, "confidence"):
            try:
                return float(h.confidence)
            except (TypeError, ValueError):
                pass

    return 0.5

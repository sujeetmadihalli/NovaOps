"""Policy engine — loads YAML rules and evaluates governance decisions.

Confidence precedence (deterministic, applied before policy matching):
  1. critic.confidence         (if > 0)
  2. root_cause.confidence_overall
  3. top_hypothesis.confidence
  4. 0.0 (default when nothing is available)
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

POLICIES_PATH = Path(__file__).parent / "policies" / "default.yaml"

# Action risk weights contribute to risk score (0–40)
_ACTION_RISK: dict = {
    "rollback_deployment": 40,
    "restart_pods": 20,
    "scale_deployment": 15,
    "noop_require_human": 0,
}

# Severity risk weights (0–30)
_SEVERITY_RISK: dict = {
    "P1": 30,
    "P2": 20,
    "P3": 10,
    "P4": 5,
}

_VALID_DECISIONS = {"ALLOW_AUTO", "REQUIRE_APPROVAL", "DENY"}


@dataclass
class GovernanceContext:
    incident_id: str
    action: str            # canonical tool name
    severity: str          # P1–P4
    confidence: float      # 0.0–1.0
    confidence_source: str # critic | root_cause_overall | top_hypothesis | default
    domain: str
    service_name: str
    namespace: str


@dataclass
class PolicyDecision:
    decision: str      # ALLOW_AUTO | REQUIRE_APPROVAL | DENY
    policy_name: str
    reason: str
    risk_score: int


def resolve_confidence(war_room) -> tuple:
    """Return (confidence: float, source: str) using deterministic precedence.

    Accepts a WarRoomResult; call from gate.py only.
    """
    if war_room.critic and war_room.critic.confidence > 0.0:
        return war_room.critic.confidence, "critic"
    if war_room.root_cause and war_room.root_cause.confidence_overall > 0.0:
        return war_room.root_cause.confidence_overall, "root_cause_overall"
    if war_room.root_cause and war_room.root_cause.top_hypothesis:
        h = war_room.root_cause.top_hypothesis
        if h.confidence > 0.0:
            return h.confidence, "top_hypothesis"
    return 0.0, "default"


def compute_risk_score(ctx: GovernanceContext) -> int:
    """Compute risk score 0–100."""
    score = _ACTION_RISK.get(ctx.action, 20)
    score += _SEVERITY_RISK.get(ctx.severity, 15)
    # Low confidence adds risk: below 75% each point costs ~0.4 risk
    if ctx.confidence < 0.75:
        score += int((0.75 - ctx.confidence) * 40)
    return min(100, score)


def _load_policies() -> list:
    try:
        with open(POLICIES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        policies = data.get("policies", [])
        logger.info(f"Loaded {len(policies)} governance policies from {POLICIES_PATH}")
        return policies
    except Exception as e:
        logger.error(f"Failed to load governance policies: {e}")
        return []


def _matches(policy: dict, ctx: GovernanceContext) -> bool:
    conditions = policy.get("conditions") or {}
    if not conditions:
        return True  # empty = catch-all

    if "actions" in conditions:
        if ctx.action not in conditions["actions"]:
            return False

    if "severities" in conditions:
        if ctx.severity not in conditions["severities"]:
            return False

    if "confidence_min" in conditions:
        if ctx.confidence < conditions["confidence_min"]:
            return False

    if "confidence_max" in conditions:
        if ctx.confidence > conditions["confidence_max"]:
            return False

    return True


class PolicyEngine:
    def __init__(self):
        self._policies = _load_policies()

    def evaluate(self, ctx: GovernanceContext) -> PolicyDecision:
        """Evaluate policies in order; first match wins."""
        risk = compute_risk_score(ctx)

        for policy in self._policies:
            if _matches(policy, ctx):
                decision = str(policy.get("decision", "REQUIRE_APPROVAL"))
                if decision not in _VALID_DECISIONS:
                    decision = "REQUIRE_APPROVAL"
                return PolicyDecision(
                    decision=decision,
                    policy_name=policy.get("name", "unknown"),
                    reason=policy.get("description", ""),
                    risk_score=risk,
                )

        # No match — safe default
        return PolicyDecision(
            decision="REQUIRE_APPROVAL",
            policy_name="default_fallback",
            reason="No policy matched — defaulting to REQUIRE_APPROVAL",
            risk_score=risk,
        )

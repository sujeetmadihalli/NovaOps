"""Escalation policy — classifies incidents for normal vs critical voice escalation.

Critical incidents trigger an outbound phone call via Amazon Connect + Nova
real-time voice conversation. Non-critical incidents follow the existing
Slack notification path.

Configuration via environment variables:
  CRITICAL_SEVERITY_LEVELS      — comma-separated severities (default: "P1")
  CRITICAL_RISK_SCORE_THRESHOLD — minimum risk score (default: 85)
  NOVAOPS_VOICE_ESCALATION_ENABLED — master switch (default: "true")
"""

import os
import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class EscalationResult:
    """Outcome of the escalation policy evaluation."""
    is_critical: bool
    reasons: List[str] = field(default_factory=list)
    severity: str = ""
    risk_score: float = 0.0


class EscalationPolicy:
    """Evaluates whether an incident warrants voice escalation."""

    def __init__(self):
        self._load_config()

    def _load_config(self):
        raw_levels = os.environ.get("CRITICAL_SEVERITY_LEVELS", "P1")
        self.critical_severities = {
            s.strip().upper() for s in raw_levels.split(",") if s.strip()
        }
        try:
            self.risk_threshold = float(
                os.environ.get("CRITICAL_RISK_SCORE_THRESHOLD", "85")
            )
        except ValueError:
            self.risk_threshold = 85.0

        self.enabled = os.environ.get(
            "NOVAOPS_VOICE_ESCALATION_ENABLED", "true"
        ).strip().lower() in {"1", "true", "yes", "on"}

    def evaluate(self, severity: str, risk_score: float,
                 governance_decision: str = "", governance_status: str = "") -> EscalationResult:
        """Determine whether an incident is critical enough for voice escalation.

        An incident is critical if the master switch is enabled AND at least one of:
          1. Severity is in the critical list (e.g. P1)
          2. Risk score meets or exceeds the threshold

        Args:
            severity: Incident severity level (P1-P4).
            risk_score: Governance risk score (0-100).
            governance_decision: Governance decision string (ALLOW_AUTO, REQUIRE_APPROVAL, DENY).
            governance_status: Mapped status (auto_executed, pending_approval, denied).

        Returns:
            EscalationResult with is_critical flag and reasons.
        """
        result = EscalationResult(
            is_critical=False,
            severity=severity,
            risk_score=risk_score,
        )

        if not self.enabled:
            logger.debug("Voice escalation disabled by config")
            return result

        # Auto-executed incidents don't need a phone call
        if governance_status == "auto_executed":
            logger.debug("Incident auto-executed, skipping voice escalation")
            return result

        norm_severity = severity.strip().upper()
        reasons = []

        if norm_severity in self.critical_severities:
            reasons.append(f"severity {norm_severity} is in critical list")

        if risk_score >= self.risk_threshold:
            reasons.append(f"risk score {risk_score} >= threshold {self.risk_threshold}")

        if reasons:
            result.is_critical = True
            result.reasons = reasons
            logger.info(
                f"ESCALATION POLICY: critical incident detected — {', '.join(reasons)}"
            )
        else:
            logger.debug(
                f"ESCALATION POLICY: not critical (severity={norm_severity}, "
                f"risk={risk_score}, threshold={self.risk_threshold})"
            )

        return result

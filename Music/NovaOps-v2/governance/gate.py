"""GovernanceGate — single control plane for all remediation execution.

Two public entry points:

  evaluate(incident_id, incident, war_room)
    Called at end of every investigation. Evaluates policies, logs the
    governance decision, and auto-executes if ALLOW_AUTO. Returns a
    GovernanceResult and writes governance.json + audit.jsonl.

  approve_and_execute(incident_id, incident)
    Called when a human approves via /api/incidents/{id}/approve.
    Loads persisted governance decision, logs HUMAN_OVERRIDE, then
    executes through the same executor. No execution bypasses this gate.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from governance.audit_log import AuditLog
from governance.policy_engine import (
    GovernanceContext,
    PolicyDecision,
    PolicyEngine,
    resolve_confidence,
)
from tools.executor import RemediationExecutor

logger = logging.getLogger(__name__)

PLANS_DIR = Path(__file__).parent.parent / "plans"


@dataclass
class GovernanceResult:
    incident_id: str
    decision: str           # ALLOW_AUTO | REQUIRE_APPROVAL | DENY
    policy_name: str
    reason: str
    risk_score: int
    severity: str
    confidence: float
    confidence_source: str
    action: str
    auto_executed: bool
    execution_result: dict
    status: str             # auto_executed | pending_approval | denied | executed | execution_failed
    evaluated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class GovernanceGate:
    def __init__(self, executor: RemediationExecutor):
        self._executor = executor
        self._engine = PolicyEngine()

    # ------------------------------------------------------------------
    # evaluate — called at end of investigation run
    # ------------------------------------------------------------------

    def evaluate(self, incident_id: str, incident: dict, war_room) -> GovernanceResult:
        """Evaluate governance policy for a newly completed investigation.

        incident must contain:
          proposed_action: {tool: str, parameters: dict}
          domain: str
        war_room is a WarRoomResult with triage, critic, root_cause populated.
        """
        audit = AuditLog(incident_id)
        ctx = self._build_context(incident_id, incident, war_room)

        # Log pre-decision pipeline events for full lineage
        self._log_pipeline_events(audit, war_room)

        decision_obj: PolicyDecision = self._engine.evaluate(ctx)
        if ctx.action == "noop_require_human" and decision_obj.decision == "ALLOW_AUTO":
            decision_obj = PolicyDecision(
                decision="REQUIRE_APPROVAL",
                policy_name=f"{decision_obj.policy_name}_guarded",
                reason="noop_require_human must remain human-gated.",
                risk_score=decision_obj.risk_score,
            )
        convergence = incident.get("convergence") or {}
        if convergence and (
            not bool(convergence.get("agree", True))
            or bool(convergence.get("jury_escalation_reasons"))
        ):
            decision_obj = PolicyDecision(
                decision="REQUIRE_APPROVAL",
                policy_name="convergence_guard_require_approval",
                reason=(
                    "Convergence guard: disagreement between War Room and Jury "
                    "or Jury escalation requires human approval."
                ),
                risk_score=decision_obj.risk_score,
            )

        audit.log("GOVERNANCE_DECISION", actor="SYSTEM", data={
            "decision": decision_obj.decision,
            "policy_name": decision_obj.policy_name,
            "reason": decision_obj.reason,
            "risk_score": decision_obj.risk_score,
            "action": ctx.action,
            "severity": ctx.severity,
            "confidence": ctx.confidence,
            "confidence_source": ctx.confidence_source,
        })

        logger.info(
            f"[{incident_id}] governance={decision_obj.decision} "
            f"policy={decision_obj.policy_name} risk={decision_obj.risk_score} "
            f"action={ctx.action} severity={ctx.severity} confidence={ctx.confidence:.2f}"
        )

        auto_executed = False
        execution_result: dict = {}
        status = "pending_approval"

        if decision_obj.decision == "ALLOW_AUTO":
            executor_incident = self._executor_incident(incident)
            audit.log("EXECUTION_STARTED", actor="SYSTEM", data={
                "tool": ctx.action,
                "trigger": "auto_governance",
            })
            execution_result = self._executor.execute(executor_incident)
            auto_executed = bool(execution_result.get("success"))
            status = "auto_executed" if auto_executed else "execution_failed"
            audit.log("EXECUTION_COMPLETE", actor="SYSTEM", data={
                "tool": ctx.action,
                "success": execution_result.get("success", False),
                "result": execution_result,
            })

        elif decision_obj.decision == "DENY":
            status = "denied"
            audit.log("EXECUTION_DENIED", actor="SYSTEM", data={
                "reason": decision_obj.reason,
                "policy_name": decision_obj.policy_name,
            })

        result = GovernanceResult(
            incident_id=incident_id,
            decision=decision_obj.decision,
            policy_name=decision_obj.policy_name,
            reason=decision_obj.reason,
            risk_score=decision_obj.risk_score,
            severity=ctx.severity,
            confidence=ctx.confidence,
            confidence_source=ctx.confidence_source,
            action=ctx.action,
            auto_executed=auto_executed,
            execution_result=execution_result,
            status=status,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )
        _save_governance(incident_id, result)
        return result

    # ------------------------------------------------------------------
    # approve_and_execute — called from /api/incidents/{id}/approve
    # ------------------------------------------------------------------

    def approve_and_execute(self, incident_id: str, incident: dict) -> GovernanceResult:
        """Human-approved execution path.

        Loads the persisted governance decision, logs HUMAN_OVERRIDE, then
        executes. The gate is the single path to execution; no call to
        executor.execute() is made outside this class.
        """
        audit = AuditLog(incident_id)
        persisted = _load_governance(incident_id)
        decision = persisted.get("decision")
        current_status = persisted.get("status")

        if not persisted:
            raise ValueError("Governance decision not found for incident.")
        if decision == "DENY":
            raise ValueError("Governance denied execution for this incident.")
        if current_status in {"auto_executed", "executed"}:
            raise ValueError(f"Incident already executed with status={current_status}.")

        audit.log("HUMAN_OVERRIDE", actor="HUMAN", data={
            "original_decision": decision or "unknown",
            "original_policy": persisted.get("policy_name", "unknown"),
            "risk_score": persisted.get("risk_score", 0),
            "action": persisted.get("action", ""),
        })

        tool = incident.get("proposed_tool", persisted.get("action", ""))
        executor_incident = self._executor_incident(incident)
        audit.log("EXECUTION_STARTED", actor="HUMAN", data={
            "tool": tool,
            "trigger": "human_approval",
        })

        execution_result = self._executor.execute(executor_incident)
        status = "executed" if execution_result.get("success") else "execution_failed"

        audit.log("EXECUTION_COMPLETE", actor="HUMAN", data={
            "tool": tool,
            "success": execution_result.get("success", False),
            "result": execution_result,
        })

        # Update governance.json with approval outcome
        updated = {
            **persisted,
            "status": status,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        inv_dir = PLANS_DIR / incident_id
        try:
            (inv_dir / "governance.json").write_text(
                json.dumps(updated, indent=2, default=str), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to update governance.json [{incident_id}]: {e}")

        return GovernanceResult(
            incident_id=incident_id,
            decision=persisted.get("decision", "REQUIRE_APPROVAL"),
            policy_name=persisted.get("policy_name", "unknown"),
            reason=persisted.get("reason", ""),
            risk_score=persisted.get("risk_score", 0),
            severity=persisted.get("severity", "P2"),
            confidence=persisted.get("confidence", 0.0),
            confidence_source=persisted.get("confidence_source", "default"),
            action=persisted.get("action", ""),
            auto_executed=False,
            execution_result=execution_result,
            status=status,
            evaluated_at=persisted.get("evaluated_at", ""),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_context(self, incident_id: str, incident: dict, war_room) -> GovernanceContext:
        # If the convergence check ran, use its adjusted confidence instead of
        # deriving it from the war room alone. Agreement boosts it; disagreement
        # lowers it — ensuring the policy engine sees the full dual-pipeline signal.
        convergence = incident.get("convergence")
        if convergence:
            confidence = convergence["adjusted_confidence"]
            confidence_source = convergence["confidence_source"]
        else:
            confidence, confidence_source = resolve_confidence(war_room)
        severity = "P2"
        if war_room.triage and war_room.triage.severity:
            severity = war_room.triage.severity

        proposed = incident.get("proposed_action") or {}
        action = proposed.get("tool") or "noop_require_human"
        params = proposed.get("parameters") or {}

        return GovernanceContext(
            incident_id=incident_id,
            action=action,
            severity=severity,
            confidence=confidence,
            confidence_source=confidence_source,
            domain=incident.get("domain", "unknown"),
            service_name=str(params.get("service_name", "")),
            namespace=str(params.get("namespace", "default")),
        )

    @staticmethod
    def _executor_incident(incident: dict) -> dict:
        """Normalize planner or DB incident shapes into executor input."""
        if "proposed_tool" in incident or "action_parameters" in incident:
            return {
                "proposed_tool": incident.get("proposed_tool", ""),
                "action_parameters": incident.get("action_parameters", {}),
                "service_name": incident.get("service_name", ""),
            }

        proposed = incident.get("proposed_action") or {}
        params = proposed.get("parameters") or {}
        return {
            "proposed_tool": proposed.get("tool", ""),
            "action_parameters": params,
            "service_name": incident.get("service_name", "") or params.get("service_name", ""),
        }

    @staticmethod
    def _log_pipeline_events(audit: AuditLog, war_room) -> None:
        """Log pre-governance pipeline events for full decision lineage."""
        if war_room.triage:
            t = war_room.triage
            audit.log("TRIAGE_COMPLETE", actor="SYSTEM", data={
                "domain": t.domain,
                "severity": t.severity,
                "service_name": t.service_name,
                "namespace": t.namespace,
            })

        if war_room.root_cause and war_room.root_cause.top_hypothesis:
            h = war_room.root_cause.top_hypothesis
            audit.log("HYPOTHESIS_FORMED", actor="SYSTEM", data={
                "rank": h.rank,
                "description": h.description[:200],
                "confidence": h.confidence,
                "recommended_action": h.recommended_action,
            })

        if war_room.critic:
            c = war_room.critic
            audit.log("CRITIC_VERDICT", actor="SYSTEM", data={
                "verdict": c.verdict,
                "confidence": c.confidence,
                "feedback": c.feedback[:200],
                "action_approved": c.action_approved,
            })


# ------------------------------------------------------------------
# Module-level persistence helpers
# ------------------------------------------------------------------

def _save_governance(incident_id: str, result: GovernanceResult) -> None:
    inv_dir = PLANS_DIR / incident_id
    if not inv_dir.exists():
        return
    try:
        (inv_dir / "governance.json").write_text(
            json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"Failed to save governance.json [{incident_id}]: {e}")


def _load_governance(incident_id: str) -> dict:
    path = PLANS_DIR / incident_id / "governance.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to load governance.json [{incident_id}]: {e}")
        return {}


def persist_fallback_governance(incident_id: str, reason: str, severity: str = "P2") -> GovernanceResult:
    """Persist a safe governance result when runtime execution fails early."""
    result = GovernanceResult(
        incident_id=incident_id,
        decision="REQUIRE_APPROVAL",
        policy_name="runtime_failure_safe_escalation",
        reason=reason,
        risk_score=100,
        severity=severity,
        confidence=0.0,
        confidence_source="default",
        action="noop_require_human",
        auto_executed=False,
        execution_result={},
        status="pending_approval",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )
    _save_governance(incident_id, result)
    return result

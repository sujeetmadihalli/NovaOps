"""NovaOps v2 — Main entry point.

Usage:
    python -m agents.main "OOM alert on payment-service in production"
"""

import os
import sys
import logging
from datetime import datetime

from agents.graph import build_war_room
from agents.artifacts import (
    build_validation_summary,
    create_investigation,
    persist_graph_artifacts,
    save_report,
    save_failure_trace,
    save_validation_summary,
)
from agents.schemas import parse_remediation, WarRoomResult
from api.history_db import get_incident_db
from governance.gate import GovernanceGate, persist_fallback_governance
from governance.audit_log import AuditLog
from governance.report import generate_governance_report
from tools.executor import RemediationExecutor
from tools.k8s_actions import KubernetesActions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("novaops")


def _extract_action_from_text(text: str) -> dict:
    """Parse remediation action from text. Used by eval runner too."""
    plan = parse_remediation(text)
    return plan.to_action_dict()


def run(
    alert_text: str,
    executor: RemediationExecutor | None = None,
    metadata: dict | None = None,
) -> dict:
    """Run the full war room investigation pipeline.

    executor — optional RemediationExecutor; if None a mock instance is created.
    Pass the real executor from api/server.py for live execution.
    """
    print(f"\n{'='*60}")
    print(f"  NovaOps v2 — Autonomous SRE War Room")
    print(f"  Alert: {alert_text}")
    print(f"  Time: {datetime.now().isoformat()}")
    print(f"{'='*60}\n")

    # Resolve executor — mock if not supplied (CLI / test mode)
    if executor is None:
        use_mock = os.environ.get("NOVAOPS_USE_MOCK", "1").strip().lower() not in {"0", "false", "no", "off"}
        executor = RemediationExecutor(KubernetesActions(use_mock=use_mock))

    # Create investigation directory
    incident_id = create_investigation(alert_text)
    print(f"[*] Investigation ID: {incident_id}")

    # Log alert receipt to audit trail
    AuditLog(incident_id).log("ALERT_RECEIVED", actor="SYSTEM", data={"alert_text": alert_text})

    # Build the multi-agent graph
    print("[*] Building war room graph...")
    graph, domain = build_war_room(alert_text)
    print(f"[*] Domain: {domain}")

    # Run the graph
    print("[*] Starting investigation...\n")
    graph_failed = False
    try:
        graph_result = graph(alert_text)
        node_texts, war_room = persist_graph_artifacts(incident_id, graph_result)
    except Exception as exc:
        graph_failed = True
        logger.exception("War room execution failed")
        node_texts = {}
        war_room = WarRoomResult()
        validation_summary = build_validation_summary(node_texts, war_room)
        save_validation_summary(incident_id, validation_summary)
        save_failure_trace(
            incident_id,
            alert_text=alert_text,
            domain=domain,
            error=str(exc),
        )
        result_text = (
            "Investigation failed during agent execution. "
            f"Escalate to human. Error: {exc}"
        )
        proposed_action = {"tool": "noop_require_human", "parameters": {}}
        report_path = save_report(
            incident_id,
            domain,
            alert_text,
            result_text,
            validation_summary=validation_summary,
        )
        gov_result = persist_fallback_governance(
            incident_id,
            reason=f"Runtime failure forced safe escalation: {exc}",
        )
        generate_governance_report(incident_id)
        return {
            "incident_id": incident_id,
            "domain": domain,
            "result": result_text[:5000],
            "proposed_action": proposed_action,
            "validation_summary": validation_summary,
            "report_path": report_path,
            "severity": gov_result.severity,
            "governance_decision": gov_result.decision,
            "governance_status": gov_result.status,
            "risk_score": gov_result.risk_score,
            "policy_name": gov_result.policy_name,
            "confidence": gov_result.confidence,
            "confidence_source": gov_result.confidence_source,
        }

    # Extract result using typed schemas
    proposed_action = war_room.proposed_action()
    result_text = war_room.summary_text()
    validation_summary = build_validation_summary(node_texts, war_room)

    if not result_text:
        result_text = str(graph_result)

    # Fallback: if schema parsing didn't find an action, try raw text
    if proposed_action.get("tool") == "noop_require_human" and result_text:
        fallback = parse_remediation(result_text)
        if fallback.is_valid():
            proposed_action = fallback.to_action_dict()

    print(f"\n{'='*60}")
    print(f"  Investigation Complete")
    print(f"{'='*60}")
    print(f"\n{result_text[:2000]}\n")

    # Save report
    report_path = save_report(
        incident_id,
        domain,
        alert_text,
        result_text,
        validation_summary=validation_summary,
    )
    print(f"[*] Report saved: {report_path}")

    # --- Stage 2: Jury Validation (independent blind deliberation) ---
    from Agent_Jury.jury_orchestrator import JuryOrchestrator
    from pipeline.convergence import check_convergence

    use_mock_env = os.environ.get("NOVAOPS_USE_MOCK", "1").strip().lower() not in {"0", "false", "no", "off"}
    jury_service = (war_room.triage.service_name if (war_room.triage and war_room.triage.service_name) else "unknown")
    jury_namespace = (war_room.triage.namespace if (war_room.triage and war_room.triage.namespace) else "default")

    print("[*] Convening jury for independent blind validation...")
    jury = JuryOrchestrator(mock_sensors=use_mock_env, mock_llm=use_mock_env)
    jury_result = jury.run(
        alert_name=alert_text,
        service_name=jury_service,
        namespace=jury_namespace,
        metadata=metadata or {},
    )
    jury_action = (jury_result.get("proposed_action") or {}).get("tool", "noop_require_human")
    jury_conf = jury_result.get("confidence", 0.0)
    print(f"[*] Jury: action={jury_action} conf={jury_conf:.2f} escalate={jury_result.get('should_escalate')}")

    # --- Stage 3: Convergence Check ---
    convergence = check_convergence(proposed_action, jury_result, war_room)
    status_label = "AGREE" if convergence["agree"] else "DISAGREE"
    print(f"[*] Convergence: {status_label} — adjusted_confidence={convergence['adjusted_confidence']:.2f}")

    AuditLog(incident_id).log("CONVERGENCE_CHECK", actor="SYSTEM", data={
        "agree": convergence["agree"],
        "war_room_action": convergence["war_room_action"],
        "jury_action": convergence["jury_action"],
        "war_room_confidence": convergence["war_room_confidence"],
        "jury_confidence": convergence["jury_confidence"],
        "adjusted_confidence": convergence["adjusted_confidence"],
        "confidence_source": convergence["confidence_source"],
        "summary": convergence["summary"],
    })

    # --- Governance gate (receives convergence-adjusted confidence) ---
    gate = GovernanceGate(executor)
    gov_result = gate.evaluate(
        incident_id,
        {"proposed_action": proposed_action, "domain": domain, "convergence": convergence},
        war_room,
    )
    generate_governance_report(incident_id)
    print(
        f"[*] Governance: decision={gov_result.decision} "
        f"risk={gov_result.risk_score}/100 policy={gov_result.policy_name}"
    )

    # Log incident to database for dashboard
    db = get_incident_db()
    # Build human-readable analysis for dashboard display
    analysis_parts = []
    if war_room.root_cause and war_room.root_cause.top_hypothesis:
        h = war_room.root_cause.top_hypothesis
        analysis_parts.append(h.description)
        if h.recommended_action:
            analysis_parts.append(f"Recommended action: {h.recommended_action}")
        analysis_parts.append(f"Confidence: {h.confidence:.0%}")
    if war_room.root_cause and war_room.root_cause.reasoning_chain:
        analysis_parts.append(f"Reasoning: {war_room.root_cause.reasoning_chain}")
    if war_room.critic and war_room.critic.feedback:
        analysis_parts.append(f"Critic: {war_room.critic.feedback}")
    analysis_display = "\n".join(analysis_parts) or result_text[:500]

    db.log_incident(
        incident_id=incident_id,
        service_name=jury_service,
        alert_name=alert_text,
        domain=domain,
        severity=gov_result.severity if gov_result else "P3",
        analysis=analysis_display,
        proposed_action=proposed_action,
        status=gov_result.status if gov_result else "UNKNOWN",
        report_path=str(report_path) if report_path else "",
    )

    return {
        "incident_id": incident_id,
        "domain": domain,
        "result": result_text[:5000],
        "proposed_action": proposed_action,
        "validation_summary": validation_summary,
        "report_path": report_path,
        # governance fields
        "severity": gov_result.severity,
        "governance_decision": gov_result.decision,
        "governance_status": gov_result.status,
        "risk_score": gov_result.risk_score,
        "policy_name": gov_result.policy_name,
        "confidence": gov_result.confidence,
        "confidence_source": gov_result.confidence_source,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m agents.main \"<alert description>\"")
        print("Example: python -m agents.main \"OOM alert on payment-service\"")
        sys.exit(1)

    alert_text = " ".join(sys.argv[1:])
    run(alert_text)


if __name__ == "__main__":
    main()

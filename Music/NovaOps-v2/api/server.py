"""FastAPI webhook server for NovaOps v2.

Endpoints:
  POST /webhook/pagerduty                    — receive alert, trigger war room
  GET  /api/incidents                        — incident history for dashboard
  GET  /api/incidents/{id}/report            — get/generate PIR
  POST /api/incidents/{id}/approve           — Ghost Mode approval (via GovernanceGate)
  GET  /api/governance/{id}/decision         — governance decision + risk score
  GET  /api/governance/{id}/audit            — append-only audit trail
  GET  /health                               — liveness probe
"""

import logging
import os
import json
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

from agents.pir_generator import generate_pir
from api.history_db import IncidentHistoryDB
from api.slack_notifier import SlackNotifier
from governance.gate import GovernanceGate
from governance.audit_log import AuditLog
from governance.report import generate_governance_report
from tools.executor import RemediationExecutor
from tools.k8s_actions import KubernetesActions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("novaops.api")


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title="NovaOps v2 — Autonomous SRE War Room")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = IncidentHistoryDB()
USE_MOCK = _env_bool("NOVAOPS_USE_MOCK", True)
notifier = SlackNotifier(use_mock=USE_MOCK)
k8s = KubernetesActions(use_mock=USE_MOCK)
executor = RemediationExecutor(k8s)
gate = GovernanceGate(executor)

# Mount dashboard if it exists
dashboard_dir = Path(__file__).parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")


class AlertPayload(BaseModel):
    alert_name: str
    service_name: str
    namespace: str = "default"
    incident_id: str = ""
    description: str = ""


def _load_validation_summary(report_path: str) -> dict:
    """Load validation summary artifact when available."""
    if not report_path:
        return {}
    report_file = Path(report_path)
    validation_path = report_file.parent / "validation.json"
    if not validation_path.exists():
        return {}
    try:
        return json.loads(validation_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to load validation summary from {validation_path}: {exc}")
        return {}


def trigger_agent_loop(payload: AlertPayload):
    """Background task: run the war room investigation."""
    from agents.main import run

    alert_text = payload.description or f"{payload.alert_name} on {payload.service_name}"
    logger.info(f"Starting investigation: {alert_text}")

    try:
        result = run(alert_text, executor=executor)

        proposed_action = result.get("proposed_action", {})
        # Map governance_status to a meaningful DB status
        gov_status = result.get("governance_status", "plan_ready")
        db_status = {
            "auto_executed": "auto_executed",
            "pending_approval": "plan_ready",
            "denied": "denied",
        }.get(gov_status, "plan_ready")

        db.log_incident(
            incident_id=result["incident_id"],
            service_name=payload.service_name,
            alert_name=payload.alert_name,
            domain=result.get("domain", ""),
            severity=result.get("severity", ""),
            analysis=result.get("result", ""),
            proposed_action=proposed_action if proposed_action else {"tool": "unknown", "parameters": {}},
            status=db_status,
            report_path=result.get("report_path", ""),
        )

        notifier.send_incident_plan(
            incident_id=result["incident_id"],
            domain=result.get("domain", ""),
            analysis=result.get("result", "")[:500],
            proposed_action=proposed_action if proposed_action else {"report_path": result.get("report_path", "")},
        )
        logger.info(
            f"Incident {result['incident_id']}: governance={result.get('governance_decision')} "
            f"risk={result.get('risk_score')}/100 status={db_status}"
        )

    except Exception as e:
        logger.critical(f"War room crashed: {e}")
        notifier.send_incident_plan(
            incident_id=payload.incident_id or "UNKNOWN",
            domain="error",
            analysis=f"CRITICAL: Agent pipeline crashed.\nException: {e}",
            proposed_action={"tool": "noop_require_human", "parameters": {}},
        )


@app.post("/webhook/pagerduty")
async def pagerduty_webhook(payload: AlertPayload, background_tasks: BackgroundTasks):
    logger.info(f"Webhook received: {payload.alert_name} on {payload.service_name}")
    background_tasks.add_task(trigger_agent_loop, payload)
    return {"status": "accepted", "message": "Investigation started"}


@app.get("/api/incidents")
def get_incidents():
    history = db.get_recent_incidents(limit=50)
    for incident in history:
        incident["validation_summary"] = _load_validation_summary(incident.get("report_path", ""))
    return {"status": "success", "count": len(history), "data": history}


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident["validation_summary"] = _load_validation_summary(incident.get("report_path", ""))
    return {"status": "success", "data": incident}


@app.post("/api/incidents/{incident_id}/approve")
def approve_incident(incident_id: str):
    """Ghost Mode: human approves the remediation plan.

    Execution is routed exclusively through GovernanceGate, which logs
    HUMAN_OVERRIDE and EXECUTION_COMPLETE to the append-only audit trail
    before returning. No executor call is made outside the gate.
    """
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        gov_result = gate.approve_and_execute(incident_id, incident)
        db.update_status(incident_id, gov_result.status)
        generate_governance_report(incident_id)
        logger.info(f"Incident {incident_id} approved: status={gov_result.status}")
        return {
            "status": gov_result.status,
            "incident_id": incident_id,
            "tool": gov_result.action,
            "risk_score": gov_result.risk_score,
            "result": gov_result.execution_result,
        }
    except ValueError as e:
        logger.warning(f"Approval rejected for incident {incident_id}: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        db.update_status(incident_id, "execution_failed")
        logger.error(f"Execution failed for incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {e}")


@app.post("/api/incidents/{incident_id}/report")
def create_pir(incident_id: str):
    """Generate a Post-Incident Report."""
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    pir = generate_pir(
        incident_id=incident_id,
        domain=incident.get("domain", "unknown"),
        alert_text=incident.get("alert_name", ""),
        analysis=incident.get("analysis", ""),
        action={
            "tool": incident.get("proposed_tool", ""),
            "parameters": incident.get("action_parameters", {}),
        },
        service_name=incident.get("service_name", ""),
    )
    db.save_pir(incident_id, pir)
    return {"status": "success", "incident_id": incident_id, "report": pir}


@app.get("/api/incidents/{incident_id}/report")
def get_pir(incident_id: str):
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if not incident.get("pir_report"):
        raise HTTPException(status_code=404, detail="No PIR generated yet")
    return {"status": "success", "report": incident["pir_report"]}


@app.get("/api/governance/{incident_id}/decision")
def get_governance_decision(incident_id: str):
    """Return the persisted governance decision and risk assessment."""
    gov_path = Path(__file__).parent.parent / "plans" / incident_id / "governance.json"
    if not gov_path.exists():
        raise HTTPException(status_code=404, detail="Governance decision not found")
    try:
        data = json.loads(gov_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read governance data: {e}")
    return {"status": "success", "incident_id": incident_id, "governance": data}


@app.get("/api/governance/{incident_id}/audit")
def get_governance_audit(incident_id: str):
    """Return the full append-only audit trail for an incident."""
    audit_log = AuditLog(incident_id)
    entries = audit_log.read_all()
    if not entries:
        raise HTTPException(status_code=404, detail="Audit trail not found or empty")
    return {
        "status": "success",
        "incident_id": incident_id,
        "entry_count": len(entries),
        "entries": entries,
    }


@app.get("/health")
def health():
    return {"status": "healthy", "version": "2.0.0"}

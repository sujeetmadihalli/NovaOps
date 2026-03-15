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
import sys
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import boto3
from botocore.config import Config

from agents.pir_generator import generate_pir
from api.history_db import get_incident_db
from api.slack_notifier import SlackNotifier
from api.escalation_policy import EscalationPolicy
from api.voice_summary import build_briefing_script, build_system_prompt
from api.connect_caller import ConnectCaller
from governance.gate import GovernanceGate
from governance.audit_log import AuditLog
from governance.report import generate_governance_report
from tools.executor import RemediationExecutor
from tools.k8s_actions import KubernetesActions

LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"


class TeeLogger:
    """Mirrors stdout/stderr to the novaops.log buffer with color tags for the Dashboard."""
    def __init__(self, stream, filename, prefix=""):
        self.terminal = stream
        self.log_file = open(filename, "a", encoding="utf-8")
        self.prefix = prefix
        self.is_new_line = True

    def write(self, message):
        self.terminal.write(message)
        formatted = ""
        for char in message:
            if self.is_new_line and char != '\n':
                formatted += self.prefix
                self.is_new_line = False
            formatted += char
            if char == '\n':
                self.is_new_line = True
        self.log_file.write(formatted)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()


def _configure_logging() -> None:
    """Ensure logs go to stdout and optionally to NOVAOPS_LOG_PATH."""
    formatter = logging.Formatter(LOG_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not root.handlers:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        root.addHandler(stream)
    else:
        for handler in root.handlers:
            if handler.formatter is None:
                handler.setFormatter(formatter)

    log_path = os.environ.get("NOVAOPS_LOG_PATH", "").strip()
    if not log_path:
        return

    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        resolved = str(path.resolve())
        # Replace stdout and stderr with TeeLogger
        sys.stdout = TeeLogger(sys.stdout, resolved, prefix="\033[0;34m[API-stdout]\033[0m ")
        sys.stderr = TeeLogger(sys.stderr, resolved, prefix="\033[0;31m[API-stderr]\033[0m ")
    except Exception as exc:
        logging.getLogger("novaops.api").warning(f"Failed to attach file logger: {exc}")


_configure_logging()
logger = logging.getLogger("novaops.api")


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title="NovaOps v2 — Autonomous SRE War Room", openapi_url="/novaops.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = get_incident_db()
USE_MOCK = _env_bool("NOVAOPS_USE_MOCK", True)
notifier = SlackNotifier(use_mock=USE_MOCK)
k8s = KubernetesActions(use_mock=USE_MOCK)
executor = RemediationExecutor(k8s)
gate = GovernanceGate(executor)
escalation_policy = EscalationPolicy()
connect_caller = ConnectCaller(use_mock=USE_MOCK)

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
    metadata: dict = Field(default_factory=dict)


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


def _try_voice_escalation(
    result: dict,
    service_name: str,
    alert_name: str,
    gov_status: str,
    proposed_action: dict,
):
    """Evaluate escalation policy and attempt outbound call if critical.

    Falls back to Slack critical escalation if the call fails.
    Ghost Mode is preserved — the call informs the engineer and asks
    for verbal approval, which routes through the same governance gate.
    """
    incident_id = result["incident_id"]
    severity = result.get("severity", "")
    risk_score = result.get("risk_score", 0)
    domain = result.get("domain", "")
    analysis = result.get("result", "")

    esc = escalation_policy.evaluate(
        severity=severity,
        risk_score=risk_score,
        governance_decision=result.get("governance_decision", ""),
        governance_status=gov_status,
    )

    if not esc.is_critical:
        return

    logger.info(f"Incident {incident_id}: CRITICAL — initiating voice escalation")

    # Build the voice briefing and system prompt
    briefing = build_briefing_script(
        incident_id=incident_id,
        service_name=service_name,
        severity=severity,
        domain=domain,
        analysis=analysis,
        proposed_action=proposed_action,
    )
    system_prompt = build_system_prompt(
        incident_id=incident_id,
        service_name=service_name,
        severity=severity,
        domain=domain,
        analysis=analysis,
        proposed_action=proposed_action,
        alert_name=alert_name,
    )

    # Attempt outbound call
    call_result = connect_caller.place_call(
        incident_id=incident_id,
        briefing_script=briefing,
        system_prompt=system_prompt,
        severity=severity,
        service_name=service_name,
    )

    if call_result.success:
        logger.info(
            f"Incident {incident_id}: outbound call placed "
            f"(contact_id={call_result.contact_id})"
        )
    else:
        logger.warning(
            f"Incident {incident_id}: outbound call failed "
            f"({call_result.error}), falling back to Slack critical escalation"
        )

    # Always send Slack critical escalation (as fallback or supplement)
    notifier.send_critical_escalation(
        incident_id=incident_id,
        service_name=service_name,
        severity=severity,
        domain=domain,
        analysis=analysis[:500],
        proposed_action=proposed_action if proposed_action else {},
        escalation_reasons=esc.reasons,
        call_failed=not call_result.success,
    )

    # Persist escalation metadata as an artifact
    _save_escalation_artifact(incident_id, esc, call_result, briefing)


def _save_escalation_artifact(escalation_id, esc_result, call_result, briefing):
    """Save voice escalation metadata to plans/{incident_id}/."""
    try:
        artifact_dir = Path(__file__).parent.parent / "plans" / escalation_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = {
            "is_critical": esc_result.is_critical,
            "reasons": esc_result.reasons,
            "severity": esc_result.severity,
            "risk_score": esc_result.risk_score,
            "call_placed": call_result.success,
            "contact_id": call_result.contact_id,
            "call_error": call_result.error,
            "briefing_script": briefing,
        }
        path = artifact_dir / "voice_escalation.json"
        path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        logger.info(f"Voice escalation artifact saved: {path}")
    except Exception as e:
        logger.warning(f"Failed to save escalation artifact: {e}")


def trigger_agent_loop(payload: AlertPayload):
    """Background task: run the war room investigation."""
    from agents.main import run

    alert_text = payload.description or f"{payload.alert_name} on {payload.service_name}"
    logger.info(f"Starting investigation: {alert_text}")

    try:
        result = run(alert_text, executor=executor, metadata=payload.metadata)

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

        # ── Voice escalation for critical incidents ─────────────────
        _try_voice_escalation(
            result=result,
            service_name=payload.service_name,
            alert_name=payload.alert_name,
            gov_status=gov_status,
            proposed_action=proposed_action,
        )

    except Exception as e:
        logger.critical(f"War room crashed: {e}")
        notifier.send_incident_plan(
            incident_id=payload.incident_id or "UNKNOWN",
            domain="error",
            analysis=f"CRITICAL: Agent pipeline crashed.\nException: {e}",
            proposed_action={"tool": "noop_require_human", "parameters": {}},
        )


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard/")


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

    pir_text, pdf_path = generate_pir(
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
    s3_key = None
    print(f"DEBUG create_pir received pdf_path from generate_pir: {pdf_path}")
    if pdf_path:
        s3_key = os.path.basename(pdf_path)
        s3_endpoint = os.environ.get("S3_ENDPOINT", None)
        client_kwargs = dict(region_name="us-east-1")
        if s3_endpoint:
            client_kwargs.update(endpoint_url=s3_endpoint, aws_access_key_id="test", aws_secret_access_key="test")
        s3_client = boto3.client("s3", **client_kwargs)
        try:
            print(f"DEBUG uploading to S3 with path {pdf_path}")
            s3_client.upload_file(pdf_path, "novaops-pir-reports", s3_key)
            print(f"DEBUG success upload to S3 with key {s3_key}")
            logger.info(f"Uploaded {s3_key} to S3 novaops-pir-reports bucket.")
        except Exception as e:
            print(f"DEBUG Failed to upload to S3: {e}")
            logger.error(f"Failed to upload {s3_key} to S3: {e}")
            s3_key = None

    db.save_pir(incident_id, pir_text, s3_key)
    return {
        "status": "success",
        "incident_id": incident_id,
        "report": pir_text,
        "pdf_path": s3_key,
    }


@app.get("/api/incidents/{incident_id}/report")
def get_pir(incident_id: str):
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if not incident.get("pir_report"):
        raise HTTPException(status_code=404, detail="No PIR generated yet")
    
    pdf_path = incident.get("report_path")
    if pdf_path == "":
        pdf_path = None
        
    return {
        "status": "success", 
        "report": incident["pir_report"],
        "pdf_path": pdf_path
    }


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


@app.get("/api/logs")
def get_live_logs():
    """Tail the unified novaops.log file for the dashboard live terminal."""
    try:
        log_path = os.environ.get("NOVAOPS_LOG_PATH", "novaops.log")
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        noise_patterns = ["GET /api/incidents", "GET /api/logs"]
        filtered = [l for l in all_lines if not any(p in l for p in noise_patterns)]
        last_lines = filtered[-500:] if len(filtered) > 500 else filtered
        return {"status": "success", "logs": last_lines}
    except FileNotFoundError:
        return {"status": "success", "logs": ["Waiting for novaops.log buffer to initialize..."]}


@app.get("/api/download-pdf")
def get_pdf_download_url(key: str):
    """Generate a presigned S3 URL for downloading a PIR PDF (LocalStack in dev, real S3 in prod)."""
    s3_endpoint = os.environ.get("S3_ENDPOINT", None)
    client_kwargs = dict(region_name="us-east-1")
    if s3_endpoint:
        client_kwargs.update(
            endpoint_url=s3_endpoint,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
    s3_client = boto3.client("s3", config=Config(signature_version="s3v4"), **client_kwargs)
    try:
        url = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": "novaops-pir-reports",
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{key}"',
            },
            ExpiresIn=3600,
        )
        return {"status": "success", "download_url": url}
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate download link")


@app.get("/health")
def health():
    return {"status": "healthy", "version": "2.0.0"}

"""FastAPI webhook server for NovaOps v2.

Endpoints:
  POST /webhook/pagerduty                    — receive alert, trigger war room
  POST /slack/actions                        — Slack interactive callbacks (approve/reject buttons)
  GET  /api/incidents                        — incident history for dashboard
  GET  /api/incidents/{id}                   — incident details for voice + tools
  GET  /api/incidents/{id}/report            — get/generate PIR
  POST /api/incidents/{id}/approve           — Ghost Mode approval (via GovernanceGate)
  POST /api/incidents/{id}/reject            — Human rejection / deny execution
  GET  /api/governance/{id}/decision         — governance decision + risk score
  GET  /api/governance/{id}/audit            — append-only audit trail
  GET  /health                               — liveness probe
"""

import logging
import os
import json
import hashlib
import hmac
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
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
S3_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
INCIDENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        # Replace stdout and stderr with TeeLogger
        sys.stdout = TeeLogger(original_stdout, resolved, prefix="\033[0;34m[API-stdout]\033[0m ")
        sys.stderr = TeeLogger(original_stderr, resolved, prefix="\033[0;31m[API-stderr]\033[0m ")

        # Ensure any existing StreamHandlers follow the new sys.stdout/sys.stderr tee wrappers.
        for handler in root.handlers:
            if isinstance(handler, logging.FileHandler):
                continue
            if isinstance(handler, logging.StreamHandler):
                handler.stream = sys.stderr if handler.stream is original_stderr else sys.stdout
    except Exception as exc:
        logging.getLogger("novaops.api").warning(f"Failed to attach file logger: {exc}")


_configure_logging()
logger = logging.getLogger("novaops.api")


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_cors_origins() -> list[str]:
    raw = os.environ.get("NOVAOPS_CORS_ORIGINS", "").strip()
    if not raw:
        # Default to local dev origins. The dashboard uses same-origin /api paths,
        # so CORS is usually only needed when opening static files directly.
        return ["http://localhost:8082", "http://127.0.0.1:8082"]

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(o, str) for o in parsed):
            return parsed
    except Exception:
        pass

    return [o.strip() for o in raw.split(",") if o.strip()]


def _require_approval_token(request: Request) -> None:
    """If NOVAOPS_APPROVAL_TOKEN is set, require the header to approve execution."""
    expected = os.environ.get("NOVAOPS_APPROVAL_TOKEN", "").strip()
    if not expected:
        return

    provided = (request.headers.get("X-NovaOps-Approval-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid approval token")


def _tail_lines(path: str, max_lines: int = 500, chunk_size: int = 8192) -> list[str]:
    """Read the last N lines of a potentially large text file efficiently."""
    if max_lines <= 0:
        return []

    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buf = b""

            while pos > 0 and buf.count(b"\n") <= max_lines:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + buf

        lines = buf.splitlines()[-max_lines:]
        return [line.decode("utf-8", errors="replace") for line in lines]
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.warning(f"Failed to tail log file {path!r}: {exc}")
        return []


def _verify_slack_signature(signing_secret: str, request: Request, raw_body: bytes) -> None:
    """Verify Slack interactive request signature (https://api.slack.com/authentication/verifying-requests-from-slack)."""
    timestamp = (request.headers.get("X-Slack-Request-Timestamp") or "").strip()
    signature = (request.headers.get("X-Slack-Signature") or "").strip()

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp")

    if abs(time.time() - ts) > 60 * 5:
        raise HTTPException(status_code=401, detail="Slack request timestamp too old")

    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    digest = hmac.new(signing_secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


def _parse_slack_payload(raw_body: bytes) -> dict:
    """Parse Slack interactive payload from x-www-form-urlencoded request bodies."""
    try:
        decoded = raw_body.decode("utf-8", errors="replace")
        parsed = urllib.parse.parse_qs(decoded)
        payload_str = (parsed.get("payload") or [""])[0]
        if not payload_str:
            raise ValueError("Missing Slack payload")
        payload = json.loads(payload_str)
        if not isinstance(payload, dict):
            raise ValueError("Invalid Slack payload")
        return payload
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid Slack payload JSON") from exc


def _slack_actor(payload: dict) -> str:
    """Best-effort attribution for audit logs when actions come from Slack."""
    user = payload.get("user") or {}
    username = (user.get("username") or user.get("name") or "").strip()
    user_id = (user.get("id") or "").strip()
    raw = username or user_id
    if not raw:
        return "SLACK"
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "_", raw)[:64]
    return f"SLACK:{safe}"


app = FastAPI(title="NovaOps v2 — Autonomous SRE War Room", openapi_url="/novaops.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
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


@app.post("/slack/actions")
async def slack_actions(request: Request, background_tasks: BackgroundTasks):
    """Slack interactive message callback for approve/reject buttons."""
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "").strip()
    if not signing_secret:
        raise HTTPException(status_code=501, detail="SLACK_SIGNING_SECRET not configured")

    raw_body = await request.body()
    _verify_slack_signature(signing_secret, request, raw_body)

    try:
        payload = _parse_slack_payload(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    actions = payload.get("actions") or []
    if not actions:
        return {"response_type": "ephemeral", "text": "No action provided."}

    value = (actions[0].get("value") or "").strip()
    actor = _slack_actor(payload)

    if value.startswith("approve_"):
        incident_id = value[len("approve_"):]
        if not INCIDENT_ID_PATTERN.fullmatch(incident_id):
            raise HTTPException(status_code=400, detail="Invalid incident id")
        background_tasks.add_task(_background_approve, incident_id, actor)
        return {"response_type": "ephemeral", "text": f"Approval received for {incident_id}. Processing..."}

    if value.startswith("reject_"):
        incident_id = value[len("reject_"):]
        if not INCIDENT_ID_PATTERN.fullmatch(incident_id):
            raise HTTPException(status_code=400, detail="Invalid incident id")
        background_tasks.add_task(_background_reject, incident_id, actor)
        return {"response_type": "ephemeral", "text": f"Rejection received for {incident_id}. Processing..."}

    return {"response_type": "ephemeral", "text": "Unknown action."}


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


def _approve_incident_internal(incident_id: str, actor: str = "HUMAN") -> dict:
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        gov_result = gate.approve_and_execute(incident_id, incident, actor=actor)
        db.update_status(incident_id, gov_result.status)
        gov_path = Path(__file__).parent.parent / "plans" / incident_id / "governance.json"
        if gov_path.exists():
            generate_governance_report(incident_id)
        logger.info(f"Incident {incident_id} approved by {actor}: status={gov_result.status}")
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


def _reject_incident_internal(incident_id: str, actor: str = "HUMAN") -> dict:
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    inv_dir = Path(__file__).parent.parent / "plans" / incident_id
    gov_path = inv_dir / "governance.json"
    if not gov_path.exists():
        raise HTTPException(status_code=409, detail="Governance decision not found for incident.")

    try:
        persisted = json.loads(gov_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read governance data: {e}")

    current_status = persisted.get("status")
    if current_status == "denied":
        # Idempotency: ensure DB matches and return success.
        db.update_status(incident_id, "denied")
        generate_governance_report(incident_id)
        return {
            "status": "denied",
            "incident_id": incident_id,
            "tool": persisted.get("action", ""),
            "risk_score": persisted.get("risk_score", 0),
        }

    if current_status in {"auto_executed", "executed"}:
        raise HTTPException(
            status_code=409,
            detail=f"Incident already executed with status={current_status}.",
        )
    if current_status == "execution_failed":
        raise HTTPException(
            status_code=409,
            detail="Incident already attempted execution and cannot be denied.",
        )

    inv_dir.mkdir(parents=True, exist_ok=True)
    AuditLog(incident_id).log("HUMAN_REJECTED", actor=actor, data={
        "original_decision": persisted.get("decision", "unknown"),
        "original_policy": persisted.get("policy_name", "unknown"),
        "risk_score": persisted.get("risk_score", 0),
        "action": persisted.get("action", ""),
    })

    updated = {
        **persisted,
        "status": "denied",
        "denied_at": datetime.now(timezone.utc).isoformat(),
        "denied_by": actor,
    }
    try:
        gov_path.write_text(json.dumps(updated, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist governance denial: {e}")

    db.update_status(incident_id, "denied")
    generate_governance_report(incident_id)
    logger.info(f"Incident {incident_id} rejected by {actor}")
    return {
        "status": "denied",
        "incident_id": incident_id,
        "tool": updated.get("action", ""),
        "risk_score": updated.get("risk_score", 0),
    }


def _background_approve(incident_id: str, actor: str) -> None:
    try:
        _approve_incident_internal(incident_id, actor=actor)
    except HTTPException as exc:
        logger.warning(f"Slack approval failed for {incident_id}: {exc.detail}")
    except Exception as exc:
        logger.error(f"Slack approval crashed for {incident_id}: {exc}")


def _background_reject(incident_id: str, actor: str) -> None:
    try:
        _reject_incident_internal(incident_id, actor=actor)
    except HTTPException as exc:
        logger.warning(f"Slack rejection failed for {incident_id}: {exc.detail}")
    except Exception as exc:
        logger.error(f"Slack rejection crashed for {incident_id}: {exc}")


@app.post("/api/incidents/{incident_id}/approve")
def approve_incident(incident_id: str, request: Request = None):
    """Ghost Mode: human approves the remediation plan.

    Execution is routed exclusively through GovernanceGate, which logs
    HUMAN_OVERRIDE and EXECUTION_COMPLETE to the append-only audit trail
    before returning. No executor call is made outside the gate.
    """
    # FastAPI injects Request at runtime; unit tests may call this function directly.
    if request is not None:
        _require_approval_token(request)
    return _approve_incident_internal(incident_id, actor="HUMAN")


@app.post("/api/incidents/{incident_id}/reject")
def reject_incident(incident_id: str, request: Request = None):
    """Ghost Mode: human rejects the remediation plan (deny execution)."""
    if request is not None:
        _require_approval_token(request)
    return _reject_incident_internal(incident_id, actor="HUMAN")


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
    logger.debug(f"create_pir received pdf_path={pdf_path!r}")
    if pdf_path:
        s3_key = os.path.basename(pdf_path)
        s3_endpoint = os.environ.get("S3_ENDPOINT", None)
        client_kwargs = dict(region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        if s3_endpoint:
            client_kwargs.update(endpoint_url=s3_endpoint, aws_access_key_id="test", aws_secret_access_key="test")
        s3_client = boto3.client("s3", **client_kwargs)
        try:
            logger.info(f"Uploading PIR PDF to S3 bucket novaops-pir-reports as key={s3_key}")
            s3_client.upload_file(pdf_path, "novaops-pir-reports", s3_key)
            logger.info(f"Uploaded {s3_key} to S3 novaops-pir-reports bucket.")
        except Exception as e:
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
    log_path = os.environ.get("NOVAOPS_LOG_PATH", "novaops.log")
    lines = _tail_lines(log_path, max_lines=2000)
    if not lines:
        return {"status": "success", "logs": ["Waiting for novaops.log buffer to initialize..."]}

    noise_patterns = ["GET /api/incidents", "GET /api/logs"]
    filtered = [l for l in lines if not any(p in l for p in noise_patterns)]
    last_lines = filtered[-500:] if len(filtered) > 500 else filtered
    return {"status": "success", "logs": last_lines}


@app.get("/api/download-pdf")
def get_pdf_download_url(key: str):
    """Generate a presigned S3 URL for downloading a PIR PDF (LocalStack in dev, real S3 in prod)."""
    if not S3_KEY_PATTERN.fullmatch(key):
        raise HTTPException(status_code=400, detail="Invalid PDF key")
    s3_endpoint = os.environ.get("S3_ENDPOINT", None)
    client_kwargs = dict(region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
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

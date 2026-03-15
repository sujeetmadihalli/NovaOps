"""Governance report generator.

Produces governance_report.md in plans/{incident_id}/ alongside the PIR
and other investigation artifacts.
"""

import json
import logging
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from governance.audit_log import AuditLog

logger = logging.getLogger(__name__)

PLANS_DIR = Path(__file__).parent.parent / "plans"


def generate_governance_report(incident_id: str) -> str:
    """Generate and save governance_report.md. Returns the report text."""
    inv_dir = PLANS_DIR / incident_id
    gov_path = inv_dir / "governance.json"
    if not gov_path.exists():
        logger.warning(f"No governance.json found for {incident_id}")
        return ""

    try:
        gov = json.loads(gov_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read governance.json [{incident_id}]: {e}")
        return ""

    audit = AuditLog(incident_id)
    entries = audit.read_all()

    table_rows = _build_audit_table(entries)
    table = "\n".join(table_rows) if table_rows else "| - | - | - | No events recorded |"

    decision = gov.get("decision", "UNKNOWN")
    risk = gov.get("risk_score", 0)
    policy_name = gov.get("policy_name", "unknown")
    reason = gov.get("reason", "")
    confidence = float(gov.get("confidence", 0.0))
    confidence_source = gov.get("confidence_source", "default")
    severity = gov.get("severity", "P2")
    action = gov.get("action", "noop_require_human")
    status = gov.get("status", "unknown")
    evaluated_at = gov.get("evaluated_at", "")
    approved_at = gov.get("approved_at", "")

    risk_bar = _risk_bar(risk)

    report = f"""# Governance Report - {incident_id}

**Generated:** {datetime.now(timezone.utc).isoformat()}
**Status:** `{status}`

---

## Risk Assessment

| Field | Value |
|---|---|
| Risk Score | {risk}/100 {risk_bar} |
| Decision | **{decision}** |
| Policy Hit | `{policy_name}` |
| Reason | {reason} |
| Severity | `{severity}` |
| Proposed Action | `{action}` |
| Confidence | {confidence:.0%} (source: `{confidence_source}`) |
| Evaluated At | {evaluated_at} |
{f"| Approved At | {approved_at} |" if approved_at else ""}

---

## Append-Only Audit Trail

| Timestamp (UTC) | Event | Actor | Detail |
|---|---|---|---|
{table}

---

## Policy Evaluation

Policies are evaluated in priority order from `governance/policies/default.yaml`.
The first matching policy determines the decision.

**Risk score formula:**
- Action weight: rollback=40, restart=20, scale=15, noop=0
- Severity weight: P1=30, P2=20, P3=10, P4=5
- Confidence penalty: `max(0, (0.75 - confidence) * 40)` for low confidence

> This audit trail is append-only. Entries are written once and never modified.
"""

    try:
        (inv_dir / "governance_report.md").write_text(report, encoding="utf-8")
        logger.info(f"Governance report saved: {inv_dir / 'governance_report.md'}")
    except Exception as e:
        logger.error(f"Failed to save governance_report.md [{incident_id}]: {e}")

    return report


def _build_audit_table(entries: list) -> list:
    rows = []
    for e in entries:
        ts = str(e.get("ts", ""))[:19].replace("T", " ")
        actor = e.get("actor", "")
        etype = e.get("event_type", "")
        data = e.get("data", {})
        detail = _summarise_event(etype, data)
        rows.append(f"| {ts} | `{etype}` | {actor} | {detail} |")
    return rows


def _summarise_event(etype: str, data: dict) -> str:
    def clip(text: str, width: int = 72) -> str:
        return textwrap.shorten(str(text), width=width, placeholder="...")

    if etype == "GOVERNANCE_DECISION":
        return (
            f"decision=**{data.get('decision')}** "
            f"policy=`{data.get('policy_name')}` "
            f"risk={data.get('risk_score')}/100"
        )
    if etype == "ALERT_RECEIVED":
        return f"alert={clip(data.get('alert_text', ''))}"
    if etype in ("EXECUTION_STARTED", "EXECUTION_COMPLETE"):
        success = data.get("success")
        suffix = f" success={success}" if success is not None else ""
        return f"tool=`{data.get('tool')}`{suffix}"
    if etype == "HUMAN_OVERRIDE":
        return (
            f"original=`{data.get('original_decision')}` "
            f"risk={data.get('risk_score')}/100"
        )
    if etype == "HUMAN_REJECTED":
        return (
            f"original=`{data.get('original_decision')}` "
            f"risk={data.get('risk_score')}/100"
        )
    if etype == "CRITIC_VERDICT":
        return f"verdict=`{data.get('verdict')}` confidence={data.get('confidence', 0):.0%}"
    if etype == "TRIAGE_COMPLETE":
        return (
            f"domain=`{data.get('domain')}` severity=`{data.get('severity')}` "
            f"service=`{data.get('service_name', 'unknown')}`"
        )
    if etype == "CONVERGENCE_CHECK":
        agree = data.get("agree")
        war_action = data.get("war_room_action")
        jury_action = data.get("jury_action")
        try:
            adj = float(data.get("adjusted_confidence", 0.0))
        except (TypeError, ValueError):
            adj = 0.0
        return f"agree={agree} war=`{war_action}` jury=`{jury_action}` adj_conf={adj:.2f}"
    if etype == "HYPOTHESIS_FORMED":
        desc = clip(data.get("description", ""))
        return f"confidence={data.get('confidence', 0):.0%} - {desc}"
    if etype == "EXECUTION_DENIED":
        return f"policy=`{data.get('policy_name')}`"
    return clip(json.dumps(data, default=str))


def _risk_bar(score: int) -> str:
    filled = round(score / 10)
    empty = 10 - filled
    return "[" + "#" * filled + "." * empty + "]"

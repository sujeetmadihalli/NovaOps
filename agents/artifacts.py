"""Filesystem-first investigation artifacts."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from agents.schemas import parse_war_room, WarRoomResult

logger = logging.getLogger(__name__)

PLANS_DIR = Path(__file__).parent.parent / "plans"
ANALYST_NODES = ("log_analyst", "metrics_analyst", "k8s_inspector", "github_analyst")


def create_investigation(alert_text: str) -> str:
    """Create a new investigation directory. Returns incident_id."""
    incident_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    inv_dir = PLANS_DIR / incident_id
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "findings").mkdir(exist_ok=True)

    # Write initial plan
    plan_md = f"""# Investigation Plan

**Incident ID:** {incident_id}
**Alert:** {alert_text}
**Started:** {datetime.now().isoformat()}
**Status:** IN PROGRESS

## Steps
- [ ] Triage: classify domain and severity
- [ ] Parallel analysis: logs, metrics, K8s, GitHub
- [ ] Root cause reasoning: synthesize findings
- [ ] Critic review: validate hypothesis
- [ ] Remediation: execute approved action
"""
    (inv_dir / "plan.md").write_text(plan_md, encoding="utf-8")
    logger.info(f"Investigation created: {incident_id}")
    return incident_id


def save_triage_result(incident_id: str, triage_output: str):
    """Save triage agent output."""
    inv_dir = PLANS_DIR / incident_id
    (inv_dir / "findings" / "triage.json").write_text(triage_output, encoding="utf-8")


def save_analyst_findings(incident_id: str, agent_name: str, findings: str):
    """Save an analyst agent's findings."""
    inv_dir = PLANS_DIR / incident_id
    (inv_dir / "findings" / f"{agent_name}.json").write_text(findings, encoding="utf-8")


def save_root_cause(incident_id: str, hypotheses: str):
    """Save root cause reasoner output."""
    inv_dir = PLANS_DIR / incident_id
    (inv_dir / "hypotheses.md").write_text(
        f"# Hypotheses\n\n```json\n{hypotheses}\n```\n", encoding="utf-8"
    )


def save_critic_review(incident_id: str, review: str):
    """Save critic verdict."""
    inv_dir = PLANS_DIR / incident_id
    (inv_dir / "findings" / "critic.json").write_text(review, encoding="utf-8")


def save_remediation_result(incident_id: str, result: str):
    """Save remediation outcome."""
    inv_dir = PLANS_DIR / incident_id
    (inv_dir / "findings" / "remediation.json").write_text(result, encoding="utf-8")


def _extract_message_text(agent_result) -> str:
    msg = getattr(agent_result, "message", None)
    if msg is None:
        return str(agent_result)

    if isinstance(msg, dict):
        content = msg.get("content", [])
    else:
        content = getattr(msg, "content", [])

    text_parts = []
    for block in (content if isinstance(content, list) else []):
        if isinstance(block, dict) and "text" in block:
            text_parts.append(str(block["text"]))
        elif isinstance(block, str):
            text_parts.append(block)
    return "\n".join(text_parts).strip() or str(agent_result)


def persist_graph_artifacts(incident_id: str, graph_result) -> tuple[dict, WarRoomResult]:
    """Persist per-node outputs and lightweight trace metadata.

    Returns (node_texts, war_room_result) where war_room_result contains
    validated, typed schemas for every agent output.
    """
    if not hasattr(graph_result, "results") or not isinstance(graph_result.results, dict):
        return {}, WarRoomResult()

    node_texts = {}
    for node_name, node_result in graph_result.results.items():
        if not node_result or not hasattr(node_result, "result"):
            continue
        node_texts[node_name] = _extract_message_text(node_result.result)

    # Parse all outputs into typed schemas
    war_room = parse_war_room(node_texts)

    if node_texts.get("triage"):
        save_triage_result(incident_id, node_texts["triage"])

    for node_name in ANALYST_NODES:
        if node_texts.get(node_name):
            save_analyst_findings(incident_id, node_name, node_texts[node_name])

    if node_texts.get("root_cause_reasoner"):
        save_root_cause(incident_id, node_texts["root_cause_reasoner"])
        inv_dir = PLANS_DIR / incident_id
        (inv_dir / "reasoning.md").write_text(
            "# Root Cause Reasoning\n\n```json\n"
            + node_texts["root_cause_reasoner"]
            + "\n```\n",
            encoding="utf-8",
        )

    if node_texts.get("critic"):
        save_critic_review(incident_id, node_texts["critic"])

    if node_texts.get("remediation_planner"):
        save_remediation_result(incident_id, node_texts["remediation_planner"])

    inv_dir = PLANS_DIR / incident_id
    loop_summary = ["# Loop Findings", ""]
    for node_name in ANALYST_NODES:
        if node_texts.get(node_name):
            loop_summary.append(f"## {node_name}")
            loop_summary.append(node_texts[node_name])
            loop_summary.append("")
    if len(loop_summary) > 2:
        (inv_dir / "findings" / "loop_01.md").write_text("\n".join(loop_summary).strip() + "\n", encoding="utf-8")

    # Save structured schemas as validated JSON
    structured = {}
    if war_room.triage:
        structured["triage"] = war_room.triage.to_dict()
    for name, af in war_room.analysts.items():
        structured[name] = af.to_dict()
    if war_room.root_cause:
        structured["root_cause"] = war_room.root_cause.to_dict()
    if war_room.critic:
        structured["critic"] = war_room.critic.to_dict()
    if war_room.remediation:
        structured["remediation"] = war_room.remediation.to_dict()
    (inv_dir / "structured.json").write_text(
        json.dumps(structured, indent=2, default=str), encoding="utf-8"
    )

    validation_summary = build_validation_summary(node_texts, war_room)
    save_validation_summary(incident_id, validation_summary)

    trace = {
        "incident_id": incident_id,
        "saved_at": datetime.now().isoformat(),
        "schema_score": validation_summary["schema_score"],
        "invalid_nodes": validation_summary["invalid_nodes"],
        "nodes": validation_summary["nodes"],
    }
    (inv_dir / "trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")
    return node_texts, war_room


def _check_schema_valid(node_name: str, war_room: WarRoomResult) -> bool:
    """Check if a node's output was successfully parsed into a valid schema."""
    if node_name == "triage":
        return war_room.triage is not None and war_room.triage.is_valid()
    if node_name in ANALYST_NODES:
        af = war_room.analysts.get(node_name)
        return af is not None and af.is_valid()
    if node_name == "root_cause_reasoner":
        return war_room.root_cause is not None and war_room.root_cause.is_valid()
    if node_name == "critic":
        return war_room.critic is not None and war_room.critic.is_valid()
    if node_name == "remediation_planner":
        return war_room.remediation is not None and war_room.remediation.is_valid()
    return False


def build_validation_summary(node_texts: dict, war_room: WarRoomResult) -> dict:
    """Build a user-visible schema validation summary for reports and API responses."""
    nodes = []
    for node_name, text in node_texts.items():
        nodes.append(
            {
                "name": node_name,
                "schema_valid": _check_schema_valid(node_name, war_room),
                "text_length": len(text),
            }
        )

    invalid_nodes = [node["name"] for node in nodes if not node["schema_valid"]]
    return {
        "total_nodes": len(nodes),
        "valid_nodes": sum(1 for node in nodes if node["schema_valid"]),
        "invalid_nodes": invalid_nodes,
        "schema_score": round(
            (sum(1 for node in nodes if node["schema_valid"]) / max(len(nodes), 1)),
            2,
        ),
        "nodes": nodes,
    }


def save_validation_summary(incident_id: str, validation_summary: dict):
    """Persist schema validation summary for dashboard/API consumption."""
    inv_dir = PLANS_DIR / incident_id
    (inv_dir / "validation.json").write_text(
        json.dumps(validation_summary, indent=2),
        encoding="utf-8",
    )


def save_failure_trace(incident_id: str, *, alert_text: str, domain: str, error: str, phase: str = "graph_execution"):
    """Persist failure metadata when the investigation cannot complete."""
    inv_dir = PLANS_DIR / incident_id
    trace = {
        "incident_id": incident_id,
        "saved_at": datetime.now().isoformat(),
        "status": "failed",
        "phase": phase,
        "domain": domain,
        "alert_text": alert_text,
        "error": error,
    }
    (inv_dir / "trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")


def save_report(
    incident_id: str,
    domain: str,
    alert_text: str,
    graph_result: str,
    validation_summary: dict | None = None,
):
    """Generate and save the final investigation report."""
    inv_dir = PLANS_DIR / incident_id
    structured = _load_structured_artifacts(inv_dir)
    validation_section = ""
    if validation_summary:
        invalid_nodes = validation_summary.get("invalid_nodes", [])
        validation_section = f"""
## Schema Validation
- Score: {validation_summary.get('schema_score', 0):.0%}
- Valid nodes: {validation_summary.get('valid_nodes', 0)}/{validation_summary.get('total_nodes', 0)}
- Invalid nodes: {", ".join(invalid_nodes) if invalid_nodes else "none"}
"""
    result_section = _build_result_section(structured, graph_result)
    report = f"""# Investigation Report

**Incident ID:** {incident_id}
**Domain:** {domain}
**Alert:** {alert_text}
**Completed:** {datetime.now().isoformat()}

## Result
{result_section}
{validation_section}

## Artifacts
- findings/triage.json
- findings/log_analyst.json
- findings/metrics_analyst.json
- findings/k8s_inspector.json
- findings/github_analyst.json
- hypotheses.md
- findings/critic.json
- findings/remediation.json
- structured.json
- validation.json
"""
    (inv_dir / "report.md").write_text(report, encoding="utf-8")

    # Update plan status
    plan_path = inv_dir / "plan.md"
    if plan_path.exists():
        plan = plan_path.read_text(encoding="utf-8")
        plan = plan.replace("IN PROGRESS", "COMPLETED")
        plan = plan.replace("- [ ]", "- [x]")
        plan_path.write_text(plan, encoding="utf-8")

    logger.info(f"Report saved: {inv_dir / 'report.md'}")
    return str(inv_dir / "report.md")


def _load_structured_artifacts(inv_dir: Path) -> dict:
    structured_path = inv_dir / "structured.json"
    if not structured_path.exists():
        return {}
    try:
        return json.loads(structured_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_result_section(structured: dict, fallback_text: str) -> str:
    triage = structured.get("triage") or {}
    root_cause = structured.get("root_cause") or {}
    critic = structured.get("critic") or {}
    remediation = structured.get("remediation") or {}

    if not structured:
        return fallback_text

    lines = []
    if triage:
        lines.extend(
            [
                "### Triage",
                f"- Domain: `{triage.get('domain', 'unknown')}`",
                f"- Severity: `{triage.get('severity', 'P2')}`",
                f"- Service: `{triage.get('service_name', 'unknown')}`",
            ]
        )
        summary = triage.get("summary")
        if summary:
            lines.append(f"- Summary: {summary}")
        lines.append("")

    hypotheses = root_cause.get("hypotheses") or []
    top_hypothesis = hypotheses[0] if hypotheses else {}
    if top_hypothesis or root_cause:
        lines.append("### Root Cause")
        if top_hypothesis:
            lines.append(f"- Top hypothesis: {top_hypothesis.get('description', 'unknown')}")
            lines.append(f"- Confidence: {top_hypothesis.get('confidence', 0.0):.0%}")
            recommended = top_hypothesis.get("recommended_action")
            if recommended:
                lines.append(f"- Recommended action: `{recommended}`")
        reasoning_chain = root_cause.get("reasoning_chain")
        if reasoning_chain:
            lines.append(f"- Reasoning: {reasoning_chain}")
        gaps = root_cause.get("gaps") or []
        if gaps:
            lines.append(f"- Gaps: {', '.join(gaps)}")
        lines.append("")

    if critic:
        lines.extend(
            [
                "### Critic Verdict",
                f"- Verdict: `{critic.get('verdict', 'UNKNOWN')}`",
                f"- Confidence: {critic.get('confidence', 0.0):.0%}",
            ]
        )
        feedback = critic.get("feedback")
        if feedback:
            lines.append(f"- Feedback: {feedback}")
        missing = critic.get("missing_evidence") or []
        if missing:
            lines.append(f"- Missing evidence: {', '.join(missing)}")
        lines.append("")

    if remediation:
        lines.extend(
            [
                "### Proposed Remediation",
                f"- Action: `{remediation.get('action_taken', 'noop_require_human')}`",
            ]
        )
        justification = remediation.get("justification")
        if justification:
            lines.append(f"- Justification: {justification}")
        parameters = remediation.get("parameters") or {}
        if parameters:
            param_text = ", ".join(f"{key}={value}" for key, value in parameters.items())
            lines.append(f"- Parameters: {param_text}")
        verification = remediation.get("verification_needed")
        if verification:
            lines.append(f"- Verify: {verification}")

    return "\n".join(lines).strip() or fallback_text

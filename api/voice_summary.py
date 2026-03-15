"""Voice summary builder — generates spoken briefing scripts and Nova system prompts.

Turns raw incident data into:
  1. A short spoken script (<=60 words) for the initial Connect TTS greeting.
  2. A full system prompt for Nova real-time conversation during the call.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

MAX_SCRIPT_WORDS = 60


def build_briefing_script(
    incident_id: str,
    service_name: str,
    severity: str,
    domain: str,
    analysis: str,
    proposed_action: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a concise spoken briefing script for TTS playback.

    The script is kept under MAX_SCRIPT_WORDS so it plays quickly and clearly
    when spoken by Polly at the start of the Connect call.

    Returns:
        A short spoken-English string suitable for TTS.
    """
    tool = "unknown action"
    if proposed_action:
        tool = proposed_action.get("tool", "unknown action")
        tool = tool.replace("_", " ")

    # Extract first sentence of analysis as the likely root cause
    root_cause = _extract_first_sentence(analysis)

    script = (
        f"NovaOps critical alert for incident {_shorten_id(incident_id)}. "
        f"Service {service_name} is experiencing a {severity} {domain.replace('_', ' ')} event. "
        f"{root_cause} "
        f"Proposed action is {tool}. "
        f"Human approval is required."
    )

    # Trim to word limit if needed
    words = script.split()
    if len(words) > MAX_SCRIPT_WORDS:
        script = " ".join(words[:MAX_SCRIPT_WORDS]) + "."

    logger.debug(f"Briefing script ({len(script.split())} words): {script}")
    return script


def build_system_prompt(
    incident_id: str,
    service_name: str,
    severity: str,
    domain: str,
    analysis: str,
    proposed_action: Optional[Dict[str, Any]] = None,
    alert_name: str = "",
) -> str:
    """Build the full system prompt for Nova real-time conversation.

    This prompt is used by the Lambda handler during the Lex-powered
    voice conversation. It follows the same pattern as sonic_call.py
    but is generated dynamically from incident data.

    Returns:
        System prompt string for bedrock.converse().
    """
    tool = "unknown"
    parameters = {}
    if proposed_action:
        tool = proposed_action.get("tool", "unknown")
        parameters = proposed_action.get("parameters", {})

    action_detail = tool.replace("_", " ")
    if parameters:
        param_parts = [f"{k}: {v}" for k, v in parameters.items()]
        action_detail += f" ({', '.join(param_parts)})"

    # Keep analysis context bounded so the prompt stays focused
    analysis_excerpt = analysis[:800] if analysis else "No analysis available."

    return f"""You are Amazon Nova, an AI voice assistant for the NovaOps SRE team.
You are on a phone call with the on-call engineer regarding a critical incident.

Incident Details:
- ID: {incident_id}
- Affected Service: {service_name}
- Alert: {alert_name}
- Severity: {severity}
- Domain: {domain}
- Analysis: {analysis_excerpt}
- Proposed Remediation: {action_detail}

Your Goal:
1. Explain the incident briefly.
2. Tell them the AI war room has proposed a remediation plan.
3. Ask if they want to approve the automated remediation.

Rules:
- Speak casually and conversationally, like a real phone call. Do not use markdown.
- Be robust: If the user tries to talk about unrelated topics, politely steer the conversation back to the incident and the remediation plan.
- If they ask for details, explain it simply using the analysis above.
- If they explicitly approve or say yes (e.g., "I approve", "go ahead", "yes do it", "sounds good"), you MUST output the exact token: [ACTION_APPROVED]
- If they reject, say no, ask to hang up, or abort (e.g., "no", "reject", "hang up", "stop", "abort"), you MUST output the exact token: [ACTION_REJECTED]
- Keep your responses under 3 sentences so it feels like a real voice conversation."""


def _extract_first_sentence(text: str) -> str:
    """Extract the first sentence from analysis text."""
    if not text:
        return "Root cause is under investigation."
    # Take first sentence, capped at reasonable length
    for end in (".", "!", "?"):
        idx = text.find(end)
        if idx != -1 and idx < 200:
            return text[: idx + 1].strip()
    # No sentence boundary found — take first ~120 chars
    truncated = text[:120].strip()
    if len(text) > 120:
        truncated += "..."
    return truncated


def _shorten_id(incident_id: str) -> str:
    """Shorten a UUID-style incident ID for spoken delivery."""
    if len(incident_id) > 12:
        return incident_id[:8]
    return incident_id

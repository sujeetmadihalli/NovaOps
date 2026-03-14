"""Typed schemas for all agent outputs with validation.

Each agent in the war room graph produces structured JSON. These dataclasses
define the contracts and provide parsing with graceful fallback.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {"rollback_deployment", "scale_deployment", "restart_pods", "noop_require_human"}
VALID_DOMAINS = {"oom", "traffic_surge", "deadlock", "config_drift", "dependency_failure", "cascading_failure", "unknown"}
VALID_SEVERITIES = {"P1", "P2", "P3", "P4"}
VALID_VERDICTS = {"PASS", "FAIL"}


def _is_non_empty_string(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: list) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _extract_json_object(text: str, required_key: str) -> dict | None:
    """Find the first JSON object in text containing the required key."""
    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and required_key in candidate:
            return candidate
    return None


def _try_parse_json(text: str) -> dict | None:
    """Try to parse a JSON object from text (handles markdown fences)."""
    if not text:
        return None
    # Strip markdown code fences
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        clean = "\n".join(lines).strip()
    try:
        obj = json.loads(clean)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Try extracting first JSON object
    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[idx:])
            if isinstance(candidate, dict):
                return candidate
        except json.JSONDecodeError:
            continue
    return None


# --- Triage ---

@dataclass
class TriageOutput:
    domain: str = "unknown"
    severity: str = "P2"
    service_name: str = ""
    namespace: str = "default"
    initial_hypotheses: List[str] = field(default_factory=list)
    key_evidence: List[str] = field(default_factory=list)
    summary: str = ""
    raw_text: str = ""

    def is_valid(self) -> bool:
        return (
            self.domain in VALID_DOMAINS
            and self.severity in VALID_SEVERITIES
            and _is_non_empty_string(self.service_name)
            and _is_string_list(self.initial_hypotheses)
            and _is_string_list(self.key_evidence)
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw_text", None)
        return d


def parse_triage(text: str) -> TriageOutput:
    obj = _try_parse_json(text)
    if not obj:
        return TriageOutput(raw_text=text)
    return TriageOutput(
        domain=str(obj.get("domain", "unknown")).lower(),
        severity=str(obj.get("severity", "P2")).upper(),
        service_name=str(obj.get("service_name", "")),
        namespace=str(obj.get("namespace", "default")),
        initial_hypotheses=obj.get("initial_hypotheses", []) if isinstance(obj.get("initial_hypotheses", []), list) else [],
        key_evidence=obj.get("key_evidence", []) if isinstance(obj.get("key_evidence", []), list) else [],
        summary=str(obj.get("summary", "")),
        raw_text=text,
    )


# --- Analyst Findings ---

@dataclass
class AnalystFindings:
    agent_name: str = ""
    findings: dict = field(default_factory=dict)
    hypothesis_support: dict = field(default_factory=dict)
    raw_text: str = ""

    def is_valid(self) -> bool:
        return (
            _is_non_empty_string(self.agent_name)
            and isinstance(self.findings, dict)
            and bool(self.findings)
            and isinstance(self.hypothesis_support, dict)
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw_text", None)
        return d


def parse_analyst_findings(text: str, agent_name: str = "") -> AnalystFindings:
    obj = _try_parse_json(text)
    if not obj:
        return AnalystFindings(agent_name=agent_name, raw_text=text)
    hypothesis_support = obj.pop("hypothesis_support", {})
    return AnalystFindings(
        agent_name=agent_name,
        findings=obj,
        hypothesis_support=hypothesis_support if isinstance(hypothesis_support, dict) else {},
        raw_text=text,
    )


# --- Root Cause Hypotheses ---

@dataclass
class Hypothesis:
    rank: int = 0
    description: str = ""
    confidence: float = 0.0
    evidence_for: List[str] = field(default_factory=list)
    evidence_against: List[str] = field(default_factory=list)
    recommended_action: str = ""

    def is_valid(self) -> bool:
        return (
            isinstance(self.rank, int)
            and self.rank > 0
            and _is_non_empty_string(self.description)
            and 0.0 <= self.confidence <= 1.0
            and _is_string_list(self.evidence_for)
            and _is_string_list(self.evidence_against)
            and _is_non_empty_string(self.recommended_action)
        )


@dataclass
class RootCauseOutput:
    hypotheses: List[Hypothesis] = field(default_factory=list)
    reasoning_chain: str = ""
    gaps: List[str] = field(default_factory=list)
    confidence_overall: float = 0.0
    raw_text: str = ""

    @property
    def top_hypothesis(self) -> Hypothesis | None:
        return self.hypotheses[0] if self.hypotheses else None

    def is_valid(self) -> bool:
        return (
            bool(self.hypotheses)
            and all(h.is_valid() for h in self.hypotheses)
            and _is_non_empty_string(self.reasoning_chain)
            and _is_string_list(self.gaps)
            and 0.0 <= self.confidence_overall <= 1.0
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw_text", None)
        return d


def parse_root_cause(text: str) -> RootCauseOutput:
    obj = _try_parse_json(text)
    if not obj:
        return RootCauseOutput(raw_text=text)

    hypotheses = []
    for h in obj.get("hypotheses", []):
        if isinstance(h, dict):
            hypotheses.append(Hypothesis(
                rank=int(h.get("rank", 0)),
                description=str(h.get("description", "")),
                confidence=_clamp_confidence(h.get("confidence", 0.0)),
                evidence_for=h.get("evidence_for", []) if isinstance(h.get("evidence_for", []), list) else [],
                evidence_against=h.get("evidence_against", []) if isinstance(h.get("evidence_against", []), list) else [],
                recommended_action=str(h.get("recommended_action", "")),
            ))

    return RootCauseOutput(
        hypotheses=hypotheses,
        reasoning_chain=str(obj.get("reasoning_chain", "")),
        gaps=obj.get("gaps", []) if isinstance(obj.get("gaps", []), list) else [],
        confidence_overall=_clamp_confidence(obj.get("confidence_overall", 0.0)),
        raw_text=text,
    )


# --- Critic Verdict ---

@dataclass
class CriticOutput:
    verdict: str = "UNKNOWN"
    confidence: float = 0.0
    feedback: str = ""
    missing_evidence: List[str] = field(default_factory=list)
    action_approved: bool = False
    raw_text: str = ""

    def is_valid(self) -> bool:
        return (
            self.verdict in VALID_VERDICTS
            and 0.0 <= self.confidence <= 1.0
            and _is_non_empty_string(self.feedback)
            and _is_string_list(self.missing_evidence)
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw_text", None)
        return d


def parse_critic(text: str) -> CriticOutput:
    obj = _try_parse_json(text)
    if not obj:
        return CriticOutput(raw_text=text)

    verdict = str(obj.get("verdict", "")).upper()
    if verdict not in VALID_VERDICTS:
        verdict = "UNKNOWN"

    return CriticOutput(
        verdict=verdict,
        confidence=_clamp_confidence(obj.get("confidence", 0.0)),
        feedback=str(obj.get("feedback", "")),
        missing_evidence=obj.get("missing_evidence", []) if isinstance(obj.get("missing_evidence", []), list) else [],
        action_approved=bool(obj.get("action_approved", False)),
        raw_text=text,
    )


# --- Remediation Plan ---

@dataclass
class RemediationPlan:
    action_taken: str = "noop_require_human"
    parameters: dict = field(default_factory=dict)
    justification: str = ""
    verification_needed: str = ""
    escalation_required: bool = False
    raw_text: str = ""

    def is_valid(self) -> bool:
        return (
            self.action_taken in ALLOWED_ACTIONS
            and isinstance(self.parameters, dict)
            and _is_non_empty_string(self.justification)
            and _is_non_empty_string(self.verification_needed)
        )

    def to_action_dict(self) -> dict:
        """Return the action in the format expected by executor/DB."""
        return {"tool": self.action_taken, "parameters": self.parameters}

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw_text", None)
        return d


def parse_remediation(text: str) -> RemediationPlan:
    if not text:
        return RemediationPlan(raw_text=text)

    # Try finding action_taken key first (most specific)
    obj = _extract_json_object(text, "action_taken")
    if not obj:
        obj = _try_parse_json(text)
    if not obj:
        return RemediationPlan(raw_text=text)

    tool = str(obj.get("action_taken") or obj.get("tool") or "noop_require_human")
    if tool not in ALLOWED_ACTIONS:
        tool = "noop_require_human"

    params = obj.get("parameters", {})
    if not isinstance(params, dict):
        params = {}

    return RemediationPlan(
        action_taken=tool,
        parameters=params,
        justification=str(obj.get("justification", "")),
        verification_needed=str(obj.get("verification_needed", "")),
        escalation_required=bool(obj.get("escalation_required", False)),
        raw_text=text,
    )


# --- Convenience: parse all node outputs from a graph run ---

@dataclass
class WarRoomResult:
    """Aggregated structured output from all agents."""
    triage: TriageOutput | None = None
    analysts: dict = field(default_factory=dict)  # agent_name -> AnalystFindings
    root_cause: RootCauseOutput | None = None
    critic: CriticOutput | None = None
    remediation: RemediationPlan | None = None

    def proposed_action(self) -> dict:
        if self.remediation and self.remediation.is_valid():
            return self.remediation.to_action_dict()
        return {"tool": "noop_require_human", "parameters": {}}

    def summary_text(self) -> str:
        parts = []
        if self.remediation and self.remediation.raw_text:
            parts.append(self.remediation.raw_text)
        if self.critic and self.critic.raw_text:
            parts.append(self.critic.raw_text)
        if self.root_cause and self.root_cause.raw_text:
            parts.append(self.root_cause.raw_text)
        return "\n".join(parts).strip()


ANALYST_NODES = ("log_analyst", "metrics_analyst", "k8s_inspector", "github_analyst")


def parse_war_room(node_texts: dict) -> WarRoomResult:
    """Parse all node text outputs into typed schemas."""
    result = WarRoomResult()

    if node_texts.get("triage"):
        result.triage = parse_triage(node_texts["triage"])

    for name in ANALYST_NODES:
        if node_texts.get(name):
            result.analysts[name] = parse_analyst_findings(node_texts[name], name)

    if node_texts.get("root_cause_reasoner"):
        result.root_cause = parse_root_cause(node_texts["root_cause_reasoner"])

    if node_texts.get("critic"):
        result.critic = parse_critic(node_texts["critic"])

    if node_texts.get("remediation_planner"):
        result.remediation = parse_remediation(node_texts["remediation_planner"])

    return result

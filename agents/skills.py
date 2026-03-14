"""Skills loader — 3-level progressive disclosure.

Level 1: SKILL.md frontmatter (name + description, ~50 tokens)
Level 2: analyst.md / remediation.md (full instructions)
Level 3: reference/ docs (on demand)
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def load_skill_index() -> dict:
    """Load skills/_meta/index.yaml — maps alert keywords to domains."""
    index_path = SKILLS_DIR / "_meta" / "index.yaml"
    with open(index_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_domain(alert_text: str) -> str:
    """Match alert text against keyword index to find the best domain."""
    index = load_skill_index()
    alert_lower = alert_text.lower()

    scores = {}
    for domain, keywords in index.get("alert_keywords", {}).items():
        score = sum(1 for kw in keywords if kw.lower() in alert_lower)
        if score > 0:
            scores[domain] = score

    if not scores:
        return "unknown"
    return max(scores, key=scores.get)


def load_skill_frontmatter(domain: str) -> Optional[str]:
    """Level 1: Load SKILL.md frontmatter (name + description)."""
    skill_path = SKILLS_DIR / "domains" / domain / "SKILL.md"
    if not skill_path.exists():
        return None
    with open(skill_path, encoding="utf-8") as f:
        return f.read()


def load_analyst_skill(domain: str) -> Optional[str]:
    """Level 2: Load domain-specific analyst playbook."""
    analyst_path = SKILLS_DIR / "domains" / domain / "analyst.md"
    if not analyst_path.exists():
        return None
    with open(analyst_path, encoding="utf-8") as f:
        return f.read()


def load_remediation_skill(domain: str) -> Optional[str]:
    """Level 2: Load domain-specific remediation playbook."""
    remediation_path = SKILLS_DIR / "domains" / domain / "remediation.md"
    if not remediation_path.exists():
        return None
    with open(remediation_path, encoding="utf-8") as f:
        return f.read()


def load_shared_skill(skill_name: str) -> Optional[str]:
    """Load a shared skill (triage, escalation)."""
    skill_path = SKILLS_DIR / "_shared" / skill_name / "SKILL.md"
    if not skill_path.exists():
        return None
    with open(skill_path, encoding="utf-8") as f:
        return f.read()


def get_all_skill_summaries() -> str:
    """Load all SKILL.md frontmatters for the triage agent's context."""
    summaries = []
    domains_dir = SKILLS_DIR / "domains"
    if not domains_dir.exists():
        return ""
    for domain_dir in sorted(domains_dir.iterdir()):
        if domain_dir.is_dir():
            skill_file = domain_dir / "SKILL.md"
            if skill_file.exists():
                with open(skill_file, encoding="utf-8") as f:
                    summaries.append(f"### {domain_dir.name}\n{f.read()}")
    return "\n\n".join(summaries)

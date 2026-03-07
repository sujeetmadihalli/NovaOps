"""Append-only audit log for governance decisions and execution events.

Each line is a newline-delimited JSON object:
  { "ts": <ISO-8601 UTC>, "event_type": str, "actor": str, "incident_id": str, "data": dict }

Written to plans/{incident_id}/audit.jsonl.
Entries are only appended, never modified.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PLANS_DIR = Path(__file__).parent.parent / "plans"

EVENT_TYPES = {
    "ALERT_RECEIVED",
    "TRIAGE_COMPLETE",
    "HYPOTHESIS_FORMED",
    "CRITIC_VERDICT",
    "GOVERNANCE_DECISION",
    "EXECUTION_STARTED",
    "EXECUTION_COMPLETE",
    "EXECUTION_DENIED",
    "HUMAN_OVERRIDE",
}


class AuditLog:
    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self._path = PLANS_DIR / incident_id / "audit.jsonl"

    def log(self, event_type: str, actor: str, data: dict) -> None:
        if event_type not in EVENT_TYPES:
            logger.warning(f"Unknown audit event type: {event_type}")
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "actor": actor,
            "incident_id": self.incident_id,
            "data": data,
        }
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error(f"Audit log write failed [{self.incident_id}]: {e}")

    def read_all(self) -> list:
        if not self._path.exists():
            return []
        entries = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            logger.error(f"Failed to read audit log [{self.incident_id}]: {e}")
        return entries

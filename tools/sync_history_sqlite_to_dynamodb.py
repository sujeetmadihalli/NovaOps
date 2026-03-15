"""Sync local SQLite incident history.db into LocalStack DynamoDB (IncidentHistory table).

Why this exists:
- The dashboard running on http://localhost:8082/dashboard/ often uses the DynamoDB backend
  (via LocalStack) when running under docker-compose.
- The offline simulation harness (`run_simulations.sh`) historically wrote incidents to SQLite
  (`history.db`) when DYNAMODB_ENDPOINT wasn't set.
- Result: simulations run successfully but never show up in the dashboard.

This script copies incidents from SQLite -> DynamoDB so the dashboard can display them.
It is idempotent: it will skip incident_ids that already exist in DynamoDB.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SyncStats:
    sqlite_rows: int = 0
    ddb_existing: int = 0
    inserted: int = 0
    skipped: int = 0


def _normalize_timestamp(ts: str) -> str:
    """Convert SQLite 'YYYY-MM-DD HH:MM:SS' to ISO-ish 'YYYY-MM-DDTHH:MM:SS' (no timezone suffix).

    The dashboard JS appends 'Z' to treat timestamps as UTC. Avoid storing an existing 'Z' here.
    """
    if not ts:
        return ""
    t = str(ts).strip()
    if t.endswith("Z"):
        t = t[:-1]
    if " " in t and "T" not in t:
        t = t.replace(" ", "T", 1)
    return t


def _rewrite_report_path(report_path: str) -> str:
    """Rewrite host paths to container-visible /app/plans paths when possible."""
    rp = (report_path or "").strip()
    if not rp:
        return ""
    if rp.startswith("/app/plans/"):
        return rp

    # Common shapes:
    # - /mnt/d/.../incident-agent/plans/<id>/report.md
    # - D:\...\incident-agent\plans\<id>\report.md
    lower = rp.lower()
    marker = "/plans/"
    if marker in lower:
        idx = lower.rfind(marker)
        suffix = rp[idx + len(marker) :].lstrip("/\\")
        return "/app/plans/" + suffix.replace("\\", "/")

    marker2 = "\\plans\\"
    if marker2 in lower:
        idx = lower.rfind(marker2)
        suffix = rp[idx + len(marker2) :].lstrip("/\\")
        return "/app/plans/" + suffix.replace("\\", "/")

    return rp


def _load_sqlite_rows(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT incident_id, timestamp, service_name, alert_name, domain, severity, analysis, "
        "proposed_tool, action_parameters, status, pir_report, report_path "
        "FROM incidents"
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def _configure_localstack_env(endpoint: str) -> None:
    # Ensure boto3 doesn't try IMDS and uses LocalStack test creds by default.
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
    os.environ.setdefault("DYNAMODB_ENDPOINT", endpoint)


def sync(sqlite_path: Path, dynamodb_endpoint: str) -> SyncStats:
    # Ensure repo root is on sys.path so imports like `api.history_db` work
    # regardless of where this script is invoked from.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from api.history_db import DynamoDBIncidentDB

    _configure_localstack_env(dynamodb_endpoint)

    stats = SyncStats()
    rows = _load_sqlite_rows(sqlite_path)
    stats.sqlite_rows = len(rows)

    ddb = DynamoDBIncidentDB(endpoint_url=dynamodb_endpoint)
    table = ddb._get_table()

    for row in rows:
        incident_id = str(row.get("incident_id", "")).strip()
        if not incident_id:
            continue

        # Skip if already present.
        try:
            existing = table.get_item(Key={"incident_id": incident_id}).get("Item")
        except Exception:
            existing = None

        if existing:
            stats.ddb_existing += 1
            stats.skipped += 1
            continue

        item = {
            "incident_id": incident_id,
            "timestamp": _normalize_timestamp(row.get("timestamp") or ""),
            "service_name": str(row.get("service_name") or ""),
            "alert_name": str(row.get("alert_name") or ""),
            "domain": str(row.get("domain") or ""),
            "severity": str(row.get("severity") or ""),
            "analysis": str(row.get("analysis") or ""),
            "proposed_tool": str(row.get("proposed_tool") or "unknown"),
            "action_parameters": str(row.get("action_parameters") or "{}"),
            "status": str(row.get("status") or "plan_ready"),
            "pir_report": str(row.get("pir_report") or ""),
            "report_path": _rewrite_report_path(str(row.get("report_path") or "")),
        }

        # Ensure action_parameters is valid JSON string.
        try:
            json.loads(item["action_parameters"])
        except Exception:
            item["action_parameters"] = "{}"

        table.put_item(Item=item)
        stats.inserted += 1

    return stats


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    sqlite_path = Path(os.environ.get("HISTORY_DB_PATH", str(repo_root / "history.db")))
    dynamodb_endpoint = os.environ.get("DYNAMODB_ENDPOINT", "http://localhost:4566").strip()

    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}")
        return 2

    stats = sync(sqlite_path, dynamodb_endpoint)
    print(
        "Synced history.db -> DynamoDB\n"
        f"- SQLite rows:   {stats.sqlite_rows}\n"
        f"- Existing DDB:  {stats.ddb_existing}\n"
        f"- Inserted:      {stats.inserted}\n"
        f"- Skipped:       {stats.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Incident history database.

Local (uvicorn):  SQLite via IncidentHistoryDB
Docker:           DynamoDB via LocalStack — DynamoDBIncidentDB

get_incident_db() returns the right backend based on DYNAMODB_ENDPOINT env var.
"""

import os
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLite backend — used for local development
# ---------------------------------------------------------------------------

_default_path = Path(__file__).parent.parent / "history.db"
DB_PATH = Path(os.environ.get("HISTORY_DB_PATH", str(_default_path)))


class IncidentHistoryDB:
    """SQLite-backed incident store for local uvicorn usage."""

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._lock = threading.Lock()
        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
        except sqlite3.OperationalError:
            import tempfile
            fallback = str(Path(tempfile.gettempdir()) / "novaops_history.db")
            logger.warning(f"Cannot open DB at {db_path!r}, falling back to {fallback}")
            self.db_path = fallback
            self._conn = sqlite3.connect(fallback, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # Improve concurrency characteristics for multi-threaded FastAPI usage.
        # If the filesystem doesn't support WAL, this is a no-op.
        try:
            with self._lock:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.Error:
            pass

        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL UNIQUE,
                    service_name TEXT NOT NULL,
                    alert_name TEXT NOT NULL,
                    domain TEXT,
                    severity TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    analysis TEXT,
                    proposed_tool TEXT,
                    action_parameters TEXT,
                    status TEXT DEFAULT 'pending',
                    pir_report TEXT,
                    report_path TEXT
                )
            """)
            self._conn.commit()

    def log_incident(self, incident_id: str, service_name: str, alert_name: str,
                     domain: str = "", severity: str = "", analysis: str = "",
                     proposed_action: dict = None, status: str = "plan_ready",
                     report_path: str = ""):
        try:
            tool = (proposed_action or {}).get("tool", "unknown")
            params = json.dumps((proposed_action or {}).get("parameters", {}))
            with self._lock:
                self._conn.execute("""
                    INSERT OR REPLACE INTO incidents
                    (incident_id, service_name, alert_name, domain, severity,
                     analysis, proposed_tool, action_parameters, status, report_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (incident_id, service_name, alert_name, domain, severity,
                      analysis, tool, params, status, report_path))
                self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to log incident: {e}")

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
                ).fetchone()
            if row:
                d = dict(row)
                try:
                    d["action_parameters"] = json.loads(d.get("action_parameters", "{}"))
                except (json.JSONDecodeError, TypeError):
                    pass
                return d
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch incident: {e}")
        return None

    def update_status(self, incident_id: str, status: str):
        with self._lock:
            self._conn.execute(
                "UPDATE incidents SET status = ? WHERE incident_id = ?",
                (status, incident_id)
            )
            self._conn.commit()

    def save_pir(self, incident_id: str, report: str, pdf_path: str = None):
        with self._lock:
            self._conn.execute(
                "UPDATE incidents SET pir_report = ?, report_path = ? WHERE incident_id = ?",
                (report, pdf_path or "", incident_id)
            )
            self._conn.commit()

    def get_recent_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM incidents ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                try:
                    d["action_parameters"] = json.loads(d.get("action_parameters", "{}"))
                except (json.JSONDecodeError, TypeError):
                    pass
                results.append(d)
            return results
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch incidents: {e}")
            return []


# ---------------------------------------------------------------------------
# DynamoDB backend — used in Docker via LocalStack
# ---------------------------------------------------------------------------

class DynamoDBIncidentDB:
    """DynamoDB-backed incident store for Docker/LocalStack deployment.

    Lazy initialization: __init__ stores only config. The actual boto3
    resource and table are created on the first method call, so server
    startup never blocks or crashes if LocalStack isn't ready yet.
    """

    TABLE_NAME = "IncidentHistory"

    def __init__(self, endpoint_url: str = None):
        self.endpoint_url = endpoint_url or os.environ.get("DYNAMODB_ENDPOINT", "http://localhost:4566")
        self._dynamodb = None
        self._table = None

    def _get_dynamodb(self):
        if not self._dynamodb:
            import boto3
            from botocore.config import Config as BotoConfig
            boto_config = BotoConfig(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1})
            # Credentials are sourced from the environment (AWS_ACCESS_KEY_ID /
            # AWS_SECRET_ACCESS_KEY in .env or host env) — no hardcoded values.
            self._dynamodb = boto3.resource(
                "dynamodb",
                endpoint_url=self.endpoint_url,
                region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
                config=boto_config,
            )
        return self._dynamodb

    def _get_table(self):
        if not self._table:
            from botocore.exceptions import ClientError
            db = self._get_dynamodb()
            try:
                db.meta.client.describe_table(TableName=self.TABLE_NAME)
                self._table = db.Table(self.TABLE_NAME)
                logger.info(f"Connected to DynamoDB table {self.TABLE_NAME}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info(f"Creating DynamoDB table {self.TABLE_NAME}...")
                    self._table = db.create_table(
                        TableName=self.TABLE_NAME,
                        KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
                        AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}],
                        BillingMode="PAY_PER_REQUEST",
                    )
                    self._table.meta.client.get_waiter("table_exists").wait(TableName=self.TABLE_NAME)
                    logger.info(f"DynamoDB table {self.TABLE_NAME} created.")
                else:
                    raise
        return self._table

    def log_incident(self, incident_id: str, service_name: str, alert_name: str,
                     domain: str = "", severity: str = "", analysis: str = "",
                     proposed_action: dict = None, status: str = "plan_ready",
                     report_path: str = ""):
        try:
            table = self._get_table()
            tool = (proposed_action or {}).get("tool", "unknown")
            params = json.dumps((proposed_action or {}).get("parameters", {}))
            table.put_item(Item={
                "incident_id": str(incident_id),
                "timestamp": datetime.utcnow().isoformat(),
                "service_name": str(service_name),
                "alert_name": str(alert_name),
                "domain": str(domain or ""),
                "severity": str(severity or ""),
                "analysis": str(analysis or ""),
                "proposed_tool": str(tool),
                "action_parameters": params,
                "status": str(status),
                "pir_report": "",
                "report_path": str(report_path or ""),
            })
            logger.info(f"Logged incident {incident_id} to DynamoDB.")
        except Exception as e:
            logger.error(f"Failed to log incident to DynamoDB: {e}")

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table()
            resp = table.get_item(Key={"incident_id": str(incident_id)})
            item = resp.get("Item")
            if item:
                try:
                    item["action_parameters"] = json.loads(item.get("action_parameters", "{}"))
                except (json.JSONDecodeError, TypeError):
                    pass
                return item
        except Exception as e:
            logger.error(f"Failed to fetch incident from DynamoDB: {e}")
        return None

    def update_status(self, incident_id: str, status: str):
        try:
            table = self._get_table()
            table.update_item(
                Key={"incident_id": str(incident_id)},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": str(status)},
            )
        except Exception as e:
            logger.error(f"Failed to update status in DynamoDB: {e}")

    def save_pir(self, incident_id: str, report: str, pdf_path: str = None):
        try:
            table = self._get_table()
            table.update_item(
                Key={"incident_id": str(incident_id)},
                UpdateExpression="SET pir_report = :r, report_path = :p",
                ExpressionAttributeValues={":r": str(report), ":p": str(pdf_path or "")},
            )
        except Exception as e:
            logger.error(f"Failed to save PIR to DynamoDB: {e}")

    def get_recent_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            table = self._get_table()
            resp = table.scan()
            items = resp.get("Items", [])
            while "LastEvaluatedKey" in resp:
                resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
                items.extend(resp.get("Items", []))
            items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            items = items[:limit]
            for item in items:
                try:
                    item["action_parameters"] = json.loads(item.get("action_parameters", "{}"))
                except (json.JSONDecodeError, TypeError):
                    pass
            return items
        except Exception as e:
            logger.error(f"Failed to fetch incidents from DynamoDB: {e}")
            return []


# ---------------------------------------------------------------------------
# Factory — pick backend based on environment
# ---------------------------------------------------------------------------

def get_incident_db():
    """Return DynamoDB backend when DYNAMODB_ENDPOINT is set (Docker), else SQLite (local)."""
    if os.environ.get("DYNAMODB_ENDPOINT"):
        return DynamoDBIncidentDB()
    return IncidentHistoryDB()

import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = "incidents.db"


class IncidentHistoryDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    service_name TEXT,
                    alert_name TEXT,
                    analysis TEXT,
                    proposed_tool TEXT,
                    action_parameters TEXT,
                    pir_report TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migrate old schema if pir_report column is missing
            try:
                conn.execute("ALTER TABLE incidents ADD COLUMN pir_report TEXT")
            except Exception:
                pass
            conn.commit()

    def log_incident(
        self,
        incident_id: str,
        service_name: str,
        alert_name: str,
        analysis: str,
        proposed_action: Dict[str, Any],
    ):
        tool = proposed_action.get("tool", "unknown")
        params = json.dumps(proposed_action.get("parameters", {}))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO incidents
                (incident_id, service_name, alert_name, analysis, proposed_tool, action_parameters)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (incident_id, service_name, alert_name, analysis, tool, params),
            )
            conn.commit()
        logger.info(f"Logged incident {incident_id} to database")

    def get_recent_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def save_pir(self, incident_id: str, pir_report: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE incidents SET pir_report = ? WHERE incident_id = ?",
                (pir_report, incident_id),
            )
            conn.commit()
        logger.info(f"Saved PIR for incident {incident_id}")

    def _row_to_dict(self, row) -> Dict[str, Any]:
        return {
            "incident_id": row["incident_id"],
            "service_name": row["service_name"],
            "alert_name": row["alert_name"],
            "analysis": row["analysis"],
            "proposed_tool": row["proposed_tool"],
            "action_parameters": json.loads(row["action_parameters"] or "{}"),
            "pir_report": row["pir_report"],
            "timestamp": row["timestamp"],
        }

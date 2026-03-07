import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class IncidentHistoryDB:
    def __init__(self, db_path: str = "history.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Creates the incidents table if it doesn't exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS incidents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        incident_id TEXT NOT NULL,
                        service_name TEXT NOT NULL,
                        alert_name TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        analysis TEXT NOT NULL,
                        proposed_tool TEXT NOT NULL,
                        action_parameters TEXT NOT NULL,
                        status TEXT NOT NULL,
                        pir_report TEXT
                    )
                ''')
                # Migration: add pir_report column if the table already existed without it
                try:
                    cursor.execute('ALTER TABLE incidents ADD COLUMN pir_report TEXT')
                except sqlite3.OperationalError:
                    pass  # Column already exists
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")

    def log_incident(self, incident_id: str, service_name: str, alert_name: str, 
                     analysis: str, proposed_action: dict, status: str = "Resolved Plan Generated"):
        """Logs a completed agent reasoning cycle into the history database."""
        try:
            tool = proposed_action.get("tool", "unknown")
            params_str = json.dumps(proposed_action.get("parameters", {}))
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO incidents 
                    (incident_id, service_name, alert_name, analysis, proposed_tool, action_parameters, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (incident_id, service_name, alert_name, analysis, tool, params_str, status))
                conn.commit()
                logger.info(f"Successfully logged incident {incident_id} to history database.")
        except sqlite3.Error as e:
            logger.error(f"Failed to log incident: {e}")

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single incident by its incident_id."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM incidents WHERE incident_id = ?', (incident_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        "id": row["id"],
                        "incident_id": row["incident_id"],
                        "service_name": row["service_name"],
                        "alert_name": row["alert_name"],
                        "timestamp": row["timestamp"],
                        "analysis": row["analysis"],
                        "proposed_tool": row["proposed_tool"],
                        "action_parameters": json.loads(row["action_parameters"]),
                        "status": row["status"],
                        "pir_report": row["pir_report"]
                    }
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch incident {incident_id}: {e}")
        return None

    def save_pir(self, incident_id: str, report: str):
        """Saves a generated Post-Incident Report to the incident record."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE incidents SET pir_report = ? WHERE incident_id = ?',
                    (report, incident_id)
                )
                conn.commit()
                logger.info(f"Saved PIR for incident {incident_id}.")
        except sqlite3.Error as e:
            logger.error(f"Failed to save PIR for {incident_id}: {e}")

    def get_recent_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves the most recent incidents formatted for the frontend dashboard."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM incidents 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                ''', (limit,))
                
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    results.append({
                        "id": row["id"],
                        "incident_id": row["incident_id"],
                        "service_name": row["service_name"],
                        "alert_name": row["alert_name"],
                        "timestamp": row["timestamp"],
                        "analysis": row["analysis"],
                        "proposed_tool": row["proposed_tool"],
                        "action_parameters": json.loads(row["action_parameters"]),
                        "status": row["status"],
                        "pir_report": row["pir_report"]
                    })
                return results
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch incident history: {e}")
            return []


import unittest
import unittest
import uuid
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi import HTTPException

from api.history_db import IncidentHistoryDB
from api import server
from governance.gate import GovernanceResult


class ApiLogicTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("tests/.tmp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / f"{uuid.uuid4().hex}.db"
        self.db = IncidentHistoryDB(str(self.db_path))

    def tearDown(self):
        self.db._conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_approve_incident_executes_scale_action(self):
        self.db.log_incident(
            incident_id="inc-1",
            service_name="checkout",
            alert_name="cpu high",
            proposed_action={
                "tool": "scale_deployment",
                "parameters": {
                    "service_name": "checkout",
                    "target_replicas": 6,
                    "namespace": "prod",
                },
            },
        )

        fake_gov = GovernanceResult(
            incident_id="inc-1", decision="REQUIRE_APPROVAL", policy_name="p2_scale_auto",
            reason="test", risk_score=35, severity="P2", confidence=0.90,
            confidence_source="critic", action="scale_deployment", auto_executed=False,
            execution_result={"success": True, "tool": "scale_deployment"},
            status="executed", evaluated_at="2026-01-01T00:00:00+00:00",
        )

        gate_mock = MagicMock()
        gate_mock.approve_and_execute.return_value = fake_gov

        with patch.object(server, "db", self.db), patch.object(server, "gate", gate_mock):
            response = server.approve_incident("inc-1")

        self.assertEqual(response["status"], "executed")
        self.assertEqual(response["tool"], "scale_deployment")
        gate_mock.approve_and_execute.assert_called_once()
        incident = self.db.get_incident("inc-1")
        self.assertEqual(incident["status"], "executed")

    def test_approve_incident_marks_failure_for_non_executable_action(self):
        self.db.log_incident(
            incident_id="inc-2",
            service_name="checkout",
            alert_name="unknown issue",
            proposed_action={"tool": "noop_require_human", "parameters": {}},
        )

        fake_gov = GovernanceResult(
            incident_id="inc-2", decision="REQUIRE_APPROVAL", policy_name="default_require_approval",
            reason="test", risk_score=20, severity="P2", confidence=0.0,
            confidence_source="default", action="noop_require_human", auto_executed=False,
            execution_result={"success": False, "message": "No executable action."},
            status="execution_failed", evaluated_at="2026-01-01T00:00:00+00:00",
        )

        gate_mock = MagicMock()
        gate_mock.approve_and_execute.return_value = fake_gov

        with patch.object(server, "db", self.db), patch.object(server, "gate", gate_mock):
            response = server.approve_incident("inc-2")

        self.assertEqual(response["status"], "execution_failed")
        incident = self.db.get_incident("inc-2")
        self.assertEqual(incident["status"], "execution_failed")

    def test_approve_incident_returns_conflict_for_denied_governance(self):
        self.db.log_incident(
            incident_id="inc-denied",
            service_name="checkout",
            alert_name="rollback blocked",
            proposed_action={"tool": "rollback_deployment", "parameters": {"service_name": "checkout"}},
        )

        gate_mock = MagicMock()
        gate_mock.approve_and_execute.side_effect = ValueError("Governance denied execution for this incident.")

        with patch.object(server, "db", self.db), patch.object(server, "gate", gate_mock):
            with self.assertRaises(HTTPException) as ctx:
                server.approve_incident("inc-denied")

        self.assertEqual(ctx.exception.status_code, 409)
        incident = self.db.get_incident("inc-denied")
        self.assertEqual(incident["status"], "plan_ready")

    def test_approve_incident_returns_conflict_for_already_executed(self):
        self.db.log_incident(
            incident_id="inc-executed",
            service_name="checkout",
            alert_name="already handled",
            proposed_action={"tool": "restart_pods", "parameters": {"service_name": "checkout"}},
            status="auto_executed",
        )

        gate_mock = MagicMock()
        gate_mock.approve_and_execute.side_effect = ValueError("Incident already executed with status=auto_executed.")

        with patch.object(server, "db", self.db), patch.object(server, "gate", gate_mock):
            with self.assertRaises(HTTPException) as ctx:
                server.approve_incident("inc-executed")

        self.assertEqual(ctx.exception.status_code, 409)
        incident = self.db.get_incident("inc-executed")
        self.assertEqual(incident["status"], "auto_executed")

    def test_reject_incident_marks_denied_and_updates_governance(self):
        incident_id = "inc-reject-1"
        self.db.log_incident(
            incident_id=incident_id,
            service_name="checkout",
            alert_name="rollback proposed",
            proposed_action={"tool": "rollback_deployment", "parameters": {"service_name": "checkout"}},
            status="pending_approval",
        )

        plans_root = Path(server.__file__).resolve().parent.parent / "plans"
        inv_dir = plans_root / incident_id
        inv_dir.mkdir(parents=True, exist_ok=True)
        gov_path = inv_dir / "governance.json"
        gov_path.write_text(
            json.dumps({
                "incident_id": incident_id,
                "decision": "REQUIRE_APPROVAL",
                "policy_name": "rollback_always_requires_approval",
                "reason": "test",
                "risk_score": 80,
                "severity": "P1",
                "confidence": 0.5,
                "confidence_source": "critic",
                "action": "rollback_deployment",
                "auto_executed": False,
                "execution_result": {},
                "status": "pending_approval",
                "evaluated_at": "2026-01-01T00:00:00+00:00",
            }, indent=2),
            encoding="utf-8",
        )

        try:
            with patch.object(server, "db", self.db):
                response = server.reject_incident(incident_id)

            self.assertEqual(response["status"], "denied")
            incident = self.db.get_incident(incident_id)
            self.assertEqual(incident["status"], "denied")

            updated = json.loads(gov_path.read_text(encoding="utf-8"))
            self.assertEqual(updated.get("status"), "denied")
            self.assertIn("denied_at", updated)
            self.assertEqual(updated.get("denied_by"), "HUMAN")

            audit_path = inv_dir / "audit.jsonl"
            self.assertTrue(audit_path.exists())
            last = audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
            entry = json.loads(last)
            self.assertEqual(entry.get("event_type"), "HUMAN_REJECTED")
        finally:
            if inv_dir.exists():
                shutil.rmtree(inv_dir, ignore_errors=True)
            # Leave plans_root if other tests/artifacts use it.

    def test_get_incident_includes_validation_summary_from_artifact(self):
        report_dir = self.temp_dir / "incident-artifacts"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "report.md"
        report_path.write_text("# report\n", encoding="utf-8")
        (report_dir / "validation.json").write_text(
            json.dumps({"schema_score": 0.75, "invalid_nodes": ["critic"]}),
            encoding="utf-8",
        )
        self.db.log_incident(
            incident_id="inc-3",
            service_name="checkout",
            alert_name="schema issue",
            proposed_action={"tool": "noop_require_human", "parameters": {}},
            report_path=str(report_path),
        )

        with patch.object(server, "db", self.db):
            response = server.get_incident("inc-3")

        self.assertEqual(response["data"]["validation_summary"]["schema_score"], 0.75)
        self.assertEqual(response["data"]["validation_summary"]["invalid_nodes"], ["critic"])


if __name__ == "__main__":
    unittest.main()

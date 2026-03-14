import shutil
import unittest
import json
from pathlib import Path
import uuid

from agents import artifacts


class _MessageObject:
    def __init__(self, content):
        self.content = content


class _AgentResult:
    def __init__(self, message):
        self.message = message


class _NodeResult:
    def __init__(self, text):
        self.result = _AgentResult(_MessageObject([{"text": text}]))


class _GraphResult:
    def __init__(self):
        self.results = {
            "triage": _NodeResult('{"domain":"oom"}'),
            "log_analyst": _NodeResult('{"error_patterns":["oom"]}'),
            "metrics_analyst": _NodeResult('{"resource_saturation":{"memory":"high"}}'),
            "k8s_inspector": _NodeResult('{"container_status":"oomkilled"}'),
            "github_analyst": _NodeResult('{"recent_deployment":true}'),
            "root_cause_reasoner": _NodeResult('{"hypotheses":[{"rank":1}]}'),
            "critic": _NodeResult(
                '{"verdict":"PASS","confidence":0.9,"feedback":"evidence is sufficient","missing_evidence":[],"action_approved":true}'
            ),
            "remediation_planner": _NodeResult(
                '{"action_taken":"restart_pods","parameters":{"service_name":"checkout"},'
                '"justification":"recycle leaking workers","verification_needed":"check restart count and errors"}'
            ),
        }


class ArtifactsLogicTests(unittest.TestCase):
    def setUp(self):
        self.original_plans_dir = artifacts.PLANS_DIR
        base_dir = Path("tests/.tmp")
        base_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = base_dir / uuid.uuid4().hex
        artifacts.PLANS_DIR = self.temp_dir
        (self.temp_dir / "inc-1" / "findings").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        artifacts.PLANS_DIR = self.original_plans_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persist_graph_artifacts_writes_expected_files(self):
        node_texts, war_room = artifacts.persist_graph_artifacts("inc-1", _GraphResult())

        self.assertIn("remediation_planner", node_texts)
        self.assertTrue((self.temp_dir / "inc-1" / "findings" / "triage.json").exists())
        self.assertTrue((self.temp_dir / "inc-1" / "hypotheses.md").exists())
        self.assertTrue((self.temp_dir / "inc-1" / "reasoning.md").exists())
        self.assertTrue((self.temp_dir / "inc-1" / "findings" / "loop_01.md").exists())
        self.assertTrue((self.temp_dir / "inc-1" / "trace.json").exists())
        self.assertTrue((self.temp_dir / "inc-1" / "structured.json").exists())
        self.assertTrue((self.temp_dir / "inc-1" / "validation.json").exists())

        # Validate structured schemas
        self.assertIsNotNone(war_room.remediation)
        self.assertEqual(war_room.remediation.action_taken, "restart_pods")
        self.assertTrue(war_room.critic.is_valid())
        self.assertEqual(war_room.critic.verdict, "PASS")

    def test_save_report_includes_schema_validation_summary(self):
        structured = {
            "triage": {
                "domain": "oom",
                "severity": "P1",
                "service_name": "checkout",
                "summary": "Pods are crashing under memory pressure.",
            },
            "root_cause": {
                "hypotheses": [
                    {
                        "description": "Memory leak after deploy",
                        "confidence": 0.83,
                        "recommended_action": "restart_pods",
                    }
                ],
                "reasoning_chain": "Memory usage rose steadily after the latest deploy.",
                "gaps": ["Heap dump"],
            },
            "critic": {
                "verdict": "PASS",
                "confidence": 0.9,
                "feedback": "Evidence is sufficient.",
            },
            "remediation": {
                "action_taken": "restart_pods",
                "parameters": {"service_name": "checkout"},
                "justification": "Recycle leaking workers.",
                "verification_needed": "Check restart count and errors.",
            },
        }
        (self.temp_dir / "inc-1" / "structured.json").write_text(json.dumps(structured), encoding="utf-8")
        validation_summary = {
            "schema_score": 0.62,
            "valid_nodes": 5,
            "total_nodes": 8,
            "invalid_nodes": ["triage", "root_cause_reasoner", "metrics_analyst"],
        }

        report_path = artifacts.save_report(
            "inc-1",
            "oom",
            "OOM alert",
            "planner output",
            validation_summary=validation_summary,
        )

        report_text = Path(report_path).read_text(encoding="utf-8")
        self.assertIn("### Triage", report_text)
        self.assertIn("Memory leak after deploy", report_text)
        self.assertIn("### Proposed Remediation", report_text)
        self.assertIn("## Schema Validation", report_text)
        self.assertIn("Invalid nodes: triage, root_cause_reasoner, metrics_analyst", report_text)


if __name__ == "__main__":
    unittest.main()

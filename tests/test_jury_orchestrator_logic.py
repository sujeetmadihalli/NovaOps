import time
import unittest
from unittest.mock import Mock, patch

from Agent_Jury.jury_orchestrator import JuryOrchestrator


class _FastJuror:
    def __init__(self, name: str, action: str = "scale_deployment", confidence: float = 0.8):
        self.name = name
        self._action = action
        self._confidence = confidence

    def deliberate(self, _incident_context):
        return {
            "juror": self.name,
            "verdict": "fast verdict",
            "recommended_action": self._action,
            "confidence": self._confidence,
            "reasoning": "fast path",
        }

    def _failure_verdict(self, reason: str):
        return {
            "juror": self.name,
            "verdict": reason,
            "recommended_action": "noop_require_human",
            "confidence": 0.0,
            "reasoning": reason,
        }


class _SlowJuror(_FastJuror):
    def deliberate(self, _incident_context):
        time.sleep(0.2)
        return super().deliberate(_incident_context)


class JuryOrchestratorLogicTests(unittest.TestCase):
    def test_run_uses_service_repo_map_from_env(self):
        with patch.dict(
            "os.environ",
            {"SERVICE_REPO_MAP": '{"checkout-service":{"owner":"acme-inc","repo":"checkout-api"}}'},
            clear=False,
        ):
            orchestrator = JuryOrchestrator(mock_sensors=True, mock_llm=True)

        orchestrator.jurors = [_FastJuror("Fast Juror")]
        orchestrator.git_agg.get_recent_commits = Mock(return_value=[])

        result = orchestrator.run(
            alert_name="P2 latency alert",
            service_name="checkout-service",
            namespace="prod",
        )

        orchestrator.git_agg.get_recent_commits.assert_called_once_with("acme-inc", "checkout-api")
        self.assertEqual(result["status"], "plan_ready")

    def test_run_prefers_metadata_repo_and_isolates_timeout(self):
        orchestrator = JuryOrchestrator(
            mock_sensors=True,
            mock_llm=True,
            service_repo_map={"checkout-service": "acme-inc/checkout-api"},
            juror_timeout_seconds=0.05,
        )
        orchestrator.jurors = [_SlowJuror("Slow Juror"), _FastJuror("Fast Juror")]
        orchestrator.git_agg.get_recent_commits = Mock(return_value=[])

        result = orchestrator.run(
            alert_name="P2 latency alert",
            service_name="checkout-service",
            namespace="prod",
            metadata={"github": {"owner": "meta-org", "repo": "meta-repo"}},
        )

        orchestrator.git_agg.get_recent_commits.assert_called_once_with("meta-org", "meta-repo")
        self.assertEqual(result["status"], "plan_ready")
        self.assertEqual(len(result["juror_verdicts"]), 2)
        slow = next(v for v in result["juror_verdicts"] if v.get("juror") == "Slow Juror")
        self.assertEqual(slow["confidence"], 0.0)
        self.assertIn("timed out", slow["verdict"])


if __name__ == "__main__":
    unittest.main()

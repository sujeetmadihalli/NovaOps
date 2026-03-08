import json
import logging
from typing import Dict, Any

from aggregator.logs import LogsAggregator
from aggregator.metrics import MetricsAggregator
from aggregator.kubernetes_state import KubernetesStateAggregator
from aggregator.github_history import GithubHistoryAggregator
from agents.knowledge_base import KnowledgeBaseRAG

from Agent_Jury.jurors.log_analyst import LogAnalystJuror
from Agent_Jury.jurors.infra_specialist import InfraSpecialistJuror
from Agent_Jury.jurors.deployment_specialist import DeploymentSpecialistJuror
from Agent_Jury.jurors.anomaly_specialist import AnomalySpecialistJuror
from Agent_Jury.judge import Judge
from Agent_Jury.escalation_gate import EscalationGate

logger = logging.getLogger(__name__)


class JuryOrchestrator:
    """
    Entry point for the Jury Agent pipeline.

    In the hybrid two-stage architecture:
    - The Jury always receives RAW incident context only — never the War Room's reasoning.
    - This preserves full independence: jurors cannot be influenced by War Room conclusions.
    - The Jury's verdict is compared against the War Room's in the Convergence Check.

    Workflow:
      1. OBSERVE    — Aggregate raw incident context (same aggregators, fresh fetch)
      2. DELIBERATE — 4 specialist jurors analyse independently in parallel
      3. JUDGE      — Judge synthesises all 4 verdicts into a binding ruling
      4. GATE       — EscalationGate flags uncertainty (result feeds Convergence Check)
    """

    def __init__(self, mock_sensors: bool = True, mock_llm: bool = False):
        self.mock_sensors = mock_sensors
        self.mock_llm = mock_llm

        self.logs_agg = LogsAggregator(use_mock=self.mock_sensors)
        self.metrics_agg = MetricsAggregator(use_mock=self.mock_sensors)
        self.k8s_agg = KubernetesStateAggregator(use_mock=self.mock_sensors)
        self.git_agg = GithubHistoryAggregator(use_mock=self.mock_sensors)
        self.rag = KnowledgeBaseRAG()

        self.jurors = [
            LogAnalystJuror(use_mock=self.mock_llm),
            InfraSpecialistJuror(use_mock=self.mock_llm),
            DeploymentSpecialistJuror(use_mock=self.mock_llm),
            AnomalySpecialistJuror(use_mock=self.mock_llm),
        ]

        self.judge = Judge(use_mock=self.mock_llm)
        self.gate = EscalationGate()

    def run(self, alert_name: str, service_name: str, namespace: str = "default") -> Dict[str, Any]:
        logger.info(f"[Jury] Convening for alert='{alert_name}' service='{service_name}'")

        # 1. OBSERVE — raw context only, independent of War Room
        try:
            incident_context = {
                "alert_name": alert_name,
                "service_name": service_name,
                "namespace": namespace,
                "logs": self.logs_agg.get_recent_errors(service_name),
                "metrics": self.metrics_agg.get_service_metrics(service_name),
                "k8s_events": self.k8s_agg.get_pod_events(namespace, service_name),
                "commits": self.git_agg.get_recent_commits("org", "repo"),
                "runbook": self.rag.search_relevant_runbook(alert_name),
            }
        except Exception as e:
            logger.error(f"[Jury] Context aggregation failed: {e}")
            return {
                "status": "failed",
                "reason": f"Context aggregation error: {e}",
                "should_escalate": True,
                "escalation_reasons": ["Jury pipeline failed during context aggregation."],
                "proposed_action": {"tool": "noop_require_human", "parameters": {}},
                "confidence": 0.0,
            }

        # 2. DELIBERATE — each juror sees only raw context
        logger.info("[Jury] Jurors deliberating independently...")
        juror_verdicts = []
        for juror in self.jurors:
            try:
                verdict = juror.deliberate(incident_context)
                juror_verdicts.append(verdict)
                logger.info(f"[Jury] {juror.name}: conf={verdict.get('confidence', 0.0):.2f} action={verdict.get('recommended_action')}")
            except Exception as e:
                logger.error(f"[Jury] {juror.name} crashed: {e}")
                juror_verdicts.append(juror._failure_verdict(f"Juror crashed: {e}"))

        # 3. JUDGE
        logger.info("[Jury] Judge deliberating...")
        try:
            judge_verdict = self.judge.deliberate(alert_name, service_name, juror_verdicts)
            logger.info(f"[Jury] Judge: conf={judge_verdict.get('confidence', 0.0):.2f} action={judge_verdict.get('proposed_action', {}).get('tool')}")
        except Exception as e:
            logger.error(f"[Jury] Judge crashed: {e}")
            judge_verdict = self.judge._failure_verdict(f"Judge crashed: {e}")

        # 4. ESCALATION GATE — result feeds Convergence Check in main.py
        gate_result = self.gate.evaluate(
            judge_verdict=judge_verdict,
            juror_verdicts=juror_verdicts,
            agent_status="plan_ready"
        )

        return {
            "status": "plan_ready",
            "juror_verdicts": juror_verdicts,
            "judge_verdict": judge_verdict,
            "gate_result": gate_result,
            # Flattened fields for convergence check
            "analysis": judge_verdict.get("final_root_cause"),
            "proposed_action": judge_verdict.get("proposed_action"),
            "confidence": judge_verdict.get("confidence", 0.0),
            "should_escalate": gate_result["should_escalate"],
            "escalation_reasons": gate_result.get("reasons", []),
        }

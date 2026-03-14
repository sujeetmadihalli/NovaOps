import unittest

from agents.schemas import (
    parse_analyst_findings,
    parse_critic,
    parse_root_cause,
    parse_triage,
    parse_war_room,
)


class SchemaLogicTests(unittest.TestCase):
    def test_parse_triage_accepts_valid_payload(self):
        triage = parse_triage(
            '{"domain":"oom","severity":"P1","service_name":"payment-service","namespace":"prod",'
            '"initial_hypotheses":["memory leak"],"key_evidence":["oomkill"],"summary":"service is failing"}'
        )
        self.assertTrue(triage.is_valid())

    def test_parse_triage_rejects_unknown_severity(self):
        triage = parse_triage(
            '{"domain":"oom","severity":"SEV0","service_name":"payment-service","initial_hypotheses":[],"key_evidence":[]}'
        )
        self.assertFalse(triage.is_valid())

    def test_parse_analyst_findings_requires_non_empty_findings(self):
        findings = parse_analyst_findings('{"hypothesis_support":{"oom":"yes"}}', "log_analyst")
        self.assertFalse(findings.is_valid())

    def test_parse_root_cause_requires_complete_hypothesis_and_reasoning(self):
        root = parse_root_cause(
            '{"hypotheses":[{"rank":1,"description":"memory leak","confidence":0.9,'
            '"evidence_for":["heap growth"],"evidence_against":[],"recommended_action":"restart"}],'
            '"reasoning_chain":"memory climbed before crash","gaps":["heap dump"],"confidence_overall":0.85}'
        )
        self.assertTrue(root.is_valid())

    def test_parse_root_cause_rejects_missing_reasoning(self):
        root = parse_root_cause(
            '{"hypotheses":[{"rank":1,"description":"memory leak","confidence":0.9,'
            '"evidence_for":["heap growth"],"evidence_against":[],"recommended_action":"restart"}],'
            '"confidence_overall":0.85}'
        )
        self.assertFalse(root.is_valid())

    def test_parse_critic_requires_feedback(self):
        critic = parse_critic('{"verdict":"PASS","confidence":0.9,"missing_evidence":[],"action_approved":true}')
        self.assertFalse(critic.is_valid())

    def test_parse_war_room_aggregates_valid_nodes(self):
        war_room = parse_war_room(
            {
                "triage": (
                    '{"domain":"oom","severity":"P1","service_name":"payment-service","namespace":"prod",'
                    '"initial_hypotheses":["memory leak"],"key_evidence":["oomkill"],"summary":"service is failing"}'
                ),
                "log_analyst": '{"error_patterns":["oom"],"hypothesis_support":{"oom":"strong"}}',
                "metrics_analyst": '{"resource_saturation":{"memory":"high"},"hypothesis_support":{"oom":"strong"}}',
                "k8s_inspector": '{"container_status":"oomkilled","hypothesis_support":{"oom":"strong"}}',
                "github_analyst": '{"recent_deployment":true,"hypothesis_support":{"oom":"weak"}}',
                "root_cause_reasoner": (
                    '{"hypotheses":[{"rank":1,"description":"memory leak","confidence":0.9,'
                    '"evidence_for":["heap growth"],"evidence_against":[],"recommended_action":"restart"}],'
                    '"reasoning_chain":"memory climbed before crash","gaps":["heap dump"],"confidence_overall":0.85}'
                ),
                "critic": '{"verdict":"PASS","confidence":0.9,"feedback":"evidence is sufficient","missing_evidence":[],"action_approved":true}',
                "remediation_planner": (
                    '{"action_taken":"restart_pods","parameters":{"service_name":"payment-service"},'
                    '"justification":"clears leaking workers","verification_needed":"confirm restarts stabilize",'
                    '"escalation_required":false}'
                ),
            }
        )
        self.assertTrue(war_room.triage.is_valid())
        self.assertTrue(war_room.root_cause.is_valid())
        self.assertTrue(war_room.critic.is_valid())
        self.assertTrue(war_room.remediation.is_valid())
        self.assertEqual(war_room.proposed_action()["tool"], "restart_pods")


if __name__ == "__main__":
    unittest.main()

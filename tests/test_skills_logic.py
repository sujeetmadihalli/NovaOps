import unittest

from agents.skills import classify_domain


class SkillsLogicTests(unittest.TestCase):
    def test_classify_domain_matches_traffic_latency_language(self):
        alert = "P2 traffic surge on checkout-service causing elevated latency and slow responses"
        self.assertEqual(classify_domain(alert), "traffic_surge")

    def test_classify_domain_preserves_existing_oom_matching(self):
        alert = "OutOfMemoryError and memory spike detected on api"
        self.assertEqual(classify_domain(alert), "oom")


if __name__ == "__main__":
    unittest.main()

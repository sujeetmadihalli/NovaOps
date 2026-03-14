import unittest
from unittest.mock import Mock

from tools.executor import RemediationExecutor


class ExecutorLogicTests(unittest.TestCase):
    def setUp(self):
        self.k8s = Mock()
        self.executor = RemediationExecutor(self.k8s)

    def test_execute_scale_deployment_uses_validated_inputs(self):
        self.k8s.scale_deployment.return_value = {"success": True, "message": "scaled"}
        incident = {
            "service_name": "checkout",
            "proposed_tool": "scale_deployment",
            "action_parameters": {
                "service_name": "checkout",
                "target_replicas": 6,
                "namespace": "prod",
            },
        }

        result = self.executor.execute(incident)

        self.assertTrue(result["success"])
        self.k8s.scale_deployment.assert_called_once_with(
            service_name="checkout",
            target_replicas=6,
            namespace="prod",
        )

    def test_execute_rejects_invalid_service_name(self):
        incident = {
            "service_name": "../checkout",
            "proposed_tool": "restart_pods",
            "action_parameters": {},
        }

        result = self.executor.execute(incident)

        self.assertFalse(result["success"])
        self.assertIn("Invalid service_name", result["message"])
        self.k8s.restart_pods.assert_not_called()

    def test_execute_rejects_non_integer_target_replicas(self):
        incident = {
            "service_name": "checkout",
            "proposed_tool": "scale_deployment",
            "action_parameters": {
                "target_replicas": "many",
            },
        }

        result = self.executor.execute(incident)

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "target_replicas must be an integer.")
        self.k8s.scale_deployment.assert_not_called()

    def test_execute_rejects_non_executable_tool(self):
        incident = {
            "service_name": "checkout",
            "proposed_tool": "noop_require_human",
            "action_parameters": {},
        }

        result = self.executor.execute(incident)

        self.assertFalse(result["success"])
        self.assertEqual(result["tool"], "noop_require_human")


if __name__ == "__main__":
    unittest.main()

"""Remediation execution policy and dispatch."""

import re
from typing import Any, Dict

from tools.k8s_actions import KubernetesActions

EXECUTABLE_TOOLS = {"rollback_deployment", "scale_deployment", "restart_pods"}
SERVICE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class RemediationExecutor:
    """Central place for validating and executing approved remediation actions."""

    def __init__(self, k8s_actions: KubernetesActions):
        self.k8s = k8s_actions

    def execute(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        tool = str(incident.get("proposed_tool") or "").strip()
        params = incident.get("action_parameters") or {}
        if not isinstance(params, dict):
            params = {}

        if tool not in EXECUTABLE_TOOLS:
            return {
                "success": False,
                "tool": tool,
                "message": "No executable action proposed. Escalate to human.",
            }

        service_name = str(params.get("service_name") or incident.get("service_name") or "").strip()
        namespace = str(params.get("namespace") or "default").strip()

        validation_error = self._validate_common(service_name, namespace)
        if validation_error:
            return {
                "success": False,
                "tool": tool,
                "message": validation_error,
            }

        if tool == "rollback_deployment":
            result = self.k8s.rollback_deployment(service_name=service_name, namespace=namespace)
        elif tool == "restart_pods":
            result = self.k8s.restart_pods(service_name=service_name, namespace=namespace)
        else:
            target_replicas = self._parse_target_replicas(params.get("target_replicas"))
            if isinstance(target_replicas, str):
                return {
                    "success": False,
                    "tool": tool,
                    "message": target_replicas,
                }
            result = self.k8s.scale_deployment(
                service_name=service_name,
                target_replicas=target_replicas,
                namespace=namespace,
            )

        return {
            "success": bool(result.get("success")),
            "tool": tool,
            "parameters": self._safe_parameters(tool, service_name, namespace, params),
            "result": result,
        }

    def _validate_common(self, service_name: str, namespace: str) -> str:
        if not SERVICE_NAME_PATTERN.fullmatch(service_name):
            return f"Invalid service_name '{service_name}' for automated execution."
        if not NAMESPACE_PATTERN.fullmatch(namespace):
            return f"Invalid namespace '{namespace}' for automated execution."
        return ""

    def _parse_target_replicas(self, raw_value: Any) -> int | str:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return "target_replicas must be an integer."
        if value < 1:
            return "target_replicas must be at least 1."
        return value

    def _safe_parameters(
        self,
        tool: str,
        service_name: str,
        namespace: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        safe = {
            "service_name": service_name,
            "namespace": namespace,
        }
        if tool == "scale_deployment":
            target_replicas = params.get("target_replicas")
            try:
                safe["target_replicas"] = int(target_replicas)
            except (TypeError, ValueError):
                pass
        return safe

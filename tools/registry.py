"""Tool registry — Strands-native @tool wrappers around K8s actions.

Each tool is a decorated function that Strands agents can call directly.
"""

import json
import logging
import os
from strands import tool
from tools.k8s_actions import KubernetesActions

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


USE_MOCK = _env_bool("NOVAOPS_USE_MOCK", True)

# Singleton K8s actions instance
_k8s = KubernetesActions(use_mock=USE_MOCK)


@tool
def rollback_deployment(service_name: str) -> str:
    """Rollback a Kubernetes deployment to its previous revision.

    Args:
        service_name: Name of the deployment to rollback
    """
    result = _k8s.rollback_deployment(service_name)
    return json.dumps(result)


@tool
def scale_deployment(service_name: str, target_replicas: int) -> str:
    """Scale a Kubernetes deployment to a target number of replicas (max 20).

    Args:
        service_name: Name of the deployment to scale
        target_replicas: Desired number of replicas
    """
    result = _k8s.scale_deployment(service_name, target_replicas)
    return json.dumps(result)


@tool
def restart_pods(service_name: str) -> str:
    """Trigger a rolling restart of pods for a deployment (clears caches, deadlocks).

    Args:
        service_name: Name of the deployment to restart
    """
    result = _k8s.restart_pods(service_name)
    return json.dumps(result)


@tool
def noop_require_human() -> str:
    """Decline to take action and escalate to a human operator.

    Use this when the root cause is unclear, involves external dependencies,
    or the risk of automated action is too high.
    """
    return json.dumps({
        "success": False,
        "message": "Agent elected to escalate. Human intervention required.",
    })


# Collect all tools for easy import
ALL_TOOLS = [rollback_deployment, scale_deployment, restart_pods, noop_require_human]

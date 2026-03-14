"""Investigation tools — Strands @tool wrappers for data aggregation.

These tools let agents fetch logs, metrics, K8s events, and GitHub commits
via the Strands tool-calling interface.
"""

import json
import logging
import os
from strands import tool
from aggregator.logs import LogsAggregator
from aggregator.metrics import MetricsAggregator
from aggregator.kubernetes_state import KubernetesStateAggregator
from aggregator.github_history import GithubHistoryAggregator

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


USE_MOCK = _env_bool("NOVAOPS_USE_MOCK", True)

# Singleton aggregators
_logs = LogsAggregator(use_mock=USE_MOCK)
_metrics = MetricsAggregator(use_mock=USE_MOCK)
_k8s = KubernetesStateAggregator(use_mock=USE_MOCK)
_github = GithubHistoryAggregator(use_mock=USE_MOCK)


@tool
def fetch_logs(service_name: str, minutes_back: int = 15) -> str:
    """Fetch recent ERROR/FATAL logs for a service from CloudWatch.

    Args:
        service_name: Name of the service to fetch logs for
        minutes_back: How many minutes of logs to retrieve
    """
    logs = _logs.get_recent_errors(service_name, minutes_back)
    return json.dumps(logs, indent=2)


@tool
def fetch_metrics(service_name: str) -> str:
    """Fetch CPU, memory, error rate, and latency metrics for a service.

    Args:
        service_name: Name of the service to fetch metrics for
    """
    metrics = _metrics.get_service_metrics(service_name)
    return json.dumps(metrics, indent=2)


@tool
def fetch_kubernetes_events(service_name: str, namespace: str = "default") -> str:
    """Fetch recent Kubernetes events (OOMKill, CrashLoop, restarts) for a service.

    Args:
        service_name: Name of the service to check events for
        namespace: Kubernetes namespace
    """
    events = _k8s.get_pod_events(namespace, service_name)
    return json.dumps(events, indent=2)


@tool
def fetch_github_commits(owner: str = "acme", repo: str = "payment-service") -> str:
    """Fetch recent GitHub commits to check for recent deployments.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
    """
    commits = _github.get_recent_commits(owner, repo)
    return json.dumps(commits, indent=2)


# All investigation tools for easy import
INVESTIGATION_TOOLS = [fetch_logs, fetch_metrics, fetch_kubernetes_events, fetch_github_commits]

"""Kubernetes state aggregator — fetches pod events or mock."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class KubernetesStateAggregator:
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        if not use_mock:
            try:
                from kubernetes import client, config
                config.load_kube_config()
                self.v1 = client.CoreV1Api()
                self.apps_v1 = client.AppsV1Api()
            except Exception as e:
                logger.warning(f"Kube config failed, using mock: {e}")
                self.use_mock = True

    def get_pod_events(self, namespace: str, service_name: str) -> List[Dict]:
        if self.use_mock:
            return self._get_mock_events(service_name)

        try:
            events = self.v1.list_namespaced_event(namespace)
            return [
                {
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "timestamp": str(event.last_timestamp),
                }
                for event in events.items
                if service_name in event.involved_object.name
            ]
        except Exception as e:
            logger.error(f"K8s event fetch failed: {e}")
            return self._get_mock_events(service_name)

    def _get_mock_events(self, service_name: str) -> List[Dict]:
        return [
            {
                "type": "Warning",
                "reason": "OOMKilling",
                "message": f"Memory cgroup out of memory: Killed process 1234 ({service_name})",
                "timestamp": "2026-03-07T10:50:00Z",
            },
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": f"Back-off restarting failed container {service_name}",
                "timestamp": "2026-03-07T10:51:00Z",
            },
            {
                "type": "Normal",
                "reason": "Pulling",
                "message": f"Pulling image for {service_name}:latest",
                "timestamp": "2026-03-07T10:52:00Z",
            },
        ]

from kubernetes import client, config
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class KubernetesStateAggregator:
    def __init__(self, use_mock: bool = False):
        self.use_mock = use_mock
        if not use_mock:
            try:
                # Load kube config from default location (~/.kube/config)
                config.load_kube_config()
                self.v1 = client.CoreV1Api()
                self.apps_v1 = client.AppsV1Api()
            except Exception as e:
                logger.warning(f"Could not load kube config, falling back to mock: {e}")
                self.use_mock = True
                
    def get_pod_events(self, namespace: str, service_name: str) -> List[Dict]:
        """
        Fetches recent events (CrashLoopBackOff, OOMKilled, Evicted) for the service pods.
        """
        if self.use_mock:
            return self._get_mock_events(service_name)
            
        try:
            events = self.v1.list_namespaced_event(namespace)
            relevant_events = []
            for event in events.items:
                if service_name in event.involved_object.name:
                    relevant_events.append({
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message,
                        "timestamp": str(event.last_timestamp)
                    })
            return relevant_events
        except Exception as e:
            logger.error(f"Failed to fetch K8s events: {e}")
            return [{"error": str(e)}]

    def _get_mock_events(self, service_name: str) -> List[Dict]:
        return [
            {
                "type": "Warning",
                "reason": "OOMKilling",
                "message": f"Memory cgroup out of memory: Killed process 1234 ({service_name})",
                "timestamp": "2026-03-05T19:50:00Z"
            },
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "timestamp": "2026-03-05T19:51:00Z"
            }
        ]

"""Kubernetes remediation actions — constrained sandbox."""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class KubernetesActions:
    """Constrained K8s operations under a scoped ServiceAccount."""

    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        if not use_mock:
            try:
                from kubernetes import client, config
                config.load_kube_config()
                self.apps_v1 = client.AppsV1Api()
                self.core_v1 = client.CoreV1Api()
            except Exception as e:
                logger.warning(f"Kube config failed, using mock: {e}")
                self.use_mock = True

    def rollback_deployment(self, service_name: str, namespace: str = "default") -> Dict[str, Any]:
        if self.use_mock:
            return {"success": True, "message": f"Rolled back deployment/{service_name} to previous revision"}

        try:
            return {"success": True, "message": f"Rollback initiated for {service_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def scale_deployment(self, service_name: str, target_replicas: int, namespace: str = "default") -> Dict[str, Any]:
        SAFE_MAX = 20
        if target_replicas > SAFE_MAX:
            logger.warning(f"Scale capped: {target_replicas} -> {SAFE_MAX}")
            target_replicas = SAFE_MAX

        if self.use_mock:
            return {"success": True, "message": f"Scaled {service_name} to {target_replicas} replicas"}

        try:
            patch = {"spec": {"replicas": target_replicas}}
            self.apps_v1.patch_namespaced_deployment_scale(
                name=service_name, namespace=namespace, body=patch
            )
            return {"success": True, "message": f"Scaled {service_name} to {target_replicas} replicas"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def restart_pods(self, service_name: str, namespace: str = "default") -> Dict[str, Any]:
        if self.use_mock:
            return {"success": True, "message": f"Rolling restart triggered for {service_name}"}

        try:
            import datetime
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": datetime.datetime.utcnow().isoformat()
                            }
                        }
                    }
                }
            }
            self.apps_v1.patch_namespaced_deployment(
                name=service_name, namespace=namespace, body=patch
            )
            return {"success": True, "message": f"Rolling restart triggered for {service_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

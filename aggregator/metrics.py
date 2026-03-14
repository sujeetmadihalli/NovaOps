"""Metrics aggregator — fetches CPU/Memory/Error rate from Prometheus or mock."""

import requests
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class MetricsAggregator:
    def __init__(self, use_mock: bool = True, prometheus_url: str = "http://localhost:9090"):
        self.use_mock = use_mock
        self.prometheus_url = prometheus_url

    def get_service_metrics(self, service_name: str) -> Dict:
        if self.use_mock:
            return self._get_mock_metrics(service_name)

        try:
            mem_query = f'sum(container_memory_working_set_bytes{{pod=~"{service_name}.*"}}) / 1024 / 1024'
            response = requests.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": mem_query},
                timeout=5,
            )
            data = response.json()
            try:
                mem_mb = round(float(data["data"]["result"][0]["value"][1]), 2)
            except (KeyError, IndexError):
                mem_mb = 0

            return {
                "cpu_utilization_percent": "N/A",
                "memory_usage_mb": mem_mb,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": "N/A",
            }
        except Exception as e:
            logger.error(f"Prometheus fetch failed: {e}")
            return self._get_mock_metrics(service_name)

    def _get_mock_metrics(self, service_name: str) -> Dict:
        return {
            "cpu_utilization_percent": 98.5,
            "memory_usage_mb": 4096,
            "memory_limit_mb": 4096,
            "error_rate_5xx_percent": 45.2,
            "network_latency_ms": 1205,
            "pod_restart_count": 7,
        }

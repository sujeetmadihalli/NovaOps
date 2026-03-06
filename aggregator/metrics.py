import requests
import json
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class MetricsAggregator:
    def __init__(self, use_mock: bool = False, prometheus_url: str = "http://localhost:9090"):
        self.use_mock = use_mock
        self.prometheus_url = prometheus_url
        
    def get_service_metrics(self, service_name: str) -> Dict:
        """
        Fetches vital metrics (CPU, Memory, Error Rate) for the service.
        """
        if self.use_mock:
            return self._get_mock_metrics(service_name)
            
        try:
            # Query Prometheus for CPU usage
            cpu_query = f'rate(container_cpu_usage_seconds_total{{container="{service_name}"}}[5m])'
            response = requests.get(f"{self.prometheus_url}/api/v1/query", params={"query": cpu_query})
            cpu_data = response.json()
            
            # Since this is a specialized agent, we would extract multiple metrics here
            # For simplicity, returning the raw Prometheus response structure
            return {
                "cpu_utilization": cpu_data,
                "memory_utilization": "Not Implemented",
                "error_rate_5xx": "Not Implemented"
            }
        except Exception as e:
            logger.error(f"Failed to fetch metrics from Prometheus: {e}")
            return {"error": str(e), "message": "Prometheus connection failed."}

    def _get_mock_metrics(self, service_name: str) -> Dict:
        return {
            "cpu_utilization_percent": 98.5,
            "memory_usage_mb": 4096,
            "memory_limit_mb": 4096,
            "error_rate_5xx_percent": 45.2,
            "network_latency_ms": 1205
        }

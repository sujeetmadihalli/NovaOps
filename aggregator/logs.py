"""Log aggregator — fetches ERROR/FATAL logs from CloudWatch or mock."""

import boto3
import logging
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger(__name__)


class LogsAggregator:
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        if not use_mock:
            self.client = boto3.client("logs", region_name="us-east-1")

    def get_recent_errors(self, service_name: str, minutes_back: int = 15) -> List[Dict]:
        if self.use_mock:
            return self._get_mock_logs(service_name)

        try:
            start_time = int((datetime.now() - timedelta(minutes=minutes_back)).timestamp() * 1000)
            response = self.client.filter_log_events(
                logGroupName=f"/aws/ecs/{service_name}",
                filterPattern="?ERROR ?FATAL ?Exception ?OOM",
                startTime=start_time,
            )
            return [
                {"timestamp": event["timestamp"], "message": event["message"]}
                for event in response.get("events", [])
            ]
        except Exception as e:
            logger.warning(f"CloudWatch fetch failed: {e}. Using mock.")
            return self._get_mock_logs(service_name)

    def _get_mock_logs(self, service_name: str) -> List[Dict]:
        now_ms = int(datetime.now().timestamp() * 1000)
        return [
            {
                "timestamp": now_ms - 300000,
                "message": f"[WARN] {service_name}: GC overhead limit approaching 90%",
            },
            {
                "timestamp": now_ms - 120000,
                "message": f"[ERROR] {service_name}: java.lang.OutOfMemoryError: Java heap space",
            },
            {
                "timestamp": now_ms - 60000,
                "message": f"[FATAL] {service_name}: Container killed by OOM killer (cgroup limit exceeded)",
            },
            {
                "timestamp": now_ms - 30000,
                "message": f"[ERROR] {service_name}: Process exited with code 137 (SIGKILL)",
            },
        ]

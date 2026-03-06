import boto3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger(__name__)

class LogsAggregator:
    def __init__(self, use_mock: bool = False):
        self.use_mock = use_mock
        if not use_mock:
            self.client = boto3.client('logs', region_name='us-east-1')
            
    def get_recent_errors(self, service_name: str, minutes_back: int = 15) -> List[Dict]:
        """
        Fetches ERROR and FATAL logs for a given service.
        """
        if self.use_mock:
            return self._get_mock_logs(service_name)
            
        try:
            # Note: This requires proper AWS credentials in the environment
            start_time = int((datetime.now() - timedelta(minutes=minutes_back)).timestamp() * 1000)
            
            response = self.client.filter_log_events(
                logGroupName=f"/aws/lambda/{service_name}", # using lambda as default for example
                filterPattern='?ERROR ?FATAL ?Exception',
                startTime=start_time
            )
            
            return [{"timestamp": event['timestamp'], "message": event['message']} for event in response.get('events', [])]
        except Exception as e:
            logger.error(f"Failed to fetch logs from CloudWatch: {e}")
            return [{"error": str(e), "message": "Failed to authenticate or fetch real logs. Mocking data recommended for local testing."}]

    def _get_mock_logs(self, service_name: str) -> List[Dict]:
        return [
            {"timestamp": int(datetime.now().timestamp() * 1000) - 60000, "message": f"[ERROR] {service_name}: Connection timeout to database"},
            {"timestamp": int(datetime.now().timestamp() * 1000) - 30000, "message": f"[FATAL] {service_name}: OutOfMemoryError: Java heap space"}
        ]

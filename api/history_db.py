import json
import logging
import os
import boto3
from typing import Dict, Any, List, Optional
from datetime import datetime
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class IncidentHistoryDB:
    def __init__(self, endpoint_url: str = None):
        # We now point by default to LocalStack port 4566
        self.endpoint_url = endpoint_url or os.environ.get('DYNAMODB_ENDPOINT', 'http://localhost:4566')
        self.table_name = 'IncidentHistory'
        self.dynamodb = None
        self.table = None

    def _get_dynamodb(self):
        """Lazily initialize the DynamoDB resource to avoid blocking startup."""
        if not self.dynamodb:
            # Short timeouts since LocalStack is local
            boto_config = BotoConfig(connect_timeout=5, read_timeout=10, retries={'max_attempts': 1})
            self.dynamodb = boto3.resource(
                'dynamodb', 
                endpoint_url=self.endpoint_url,
                region_name='us-east-1',
                aws_access_key_id='test',
                aws_secret_access_key='test',
                config=boto_config
            )
        return self.dynamodb

    def _get_table(self):
        if not self.table:
            db = self._get_dynamodb()
            try:
                db.meta.client.describe_table(TableName=self.table_name)
                self.table = db.Table(self.table_name)
                logger.info(f"Connected to existing DynamoDB table {self.table_name}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    logger.info(f"Creating DynamoDB table {self.table_name}...")
                    try:
                        self.table = db.create_table(
                            TableName=self.table_name,
                            KeySchema=[
                                {'AttributeName': 'incident_id', 'KeyType': 'HASH'}
                            ],
                            AttributeDefinitions=[
                                {'AttributeName': 'incident_id', 'AttributeType': 'S'},
                                {'AttributeName': 'timestamp', 'AttributeType': 'S'}
                            ],
                            GlobalSecondaryIndexes=[
                                {
                                    'IndexName': 'TimeIndex',
                                    'KeySchema': [
                                        {'AttributeName': 'incident_id', 'KeyType': 'HASH'},
                                        {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                                    ],
                                    'Projection': {'ProjectionType': 'ALL'},
                                    'ProvisionedThroughput': {
                                        'ReadCapacityUnits': 5,
                                        'WriteCapacityUnits': 5
                                    }
                                }
                            ],
                            ProvisionedThroughput={
                                'ReadCapacityUnits': 5,
                                'WriteCapacityUnits': 5
                            }
                        )
                        self.table.meta.client.get_waiter('table_exists').wait(TableName=self.table_name)
                        logger.info(f"DynamoDB table {self.table_name} created successfully.")
                    except ClientError as ce:
                        logger.error(f"Failed to create table: {ce}")
                        raise
                else:
                    logger.error(f"Error checking table: {e}")
                    raise
        return self.table

    def log_incident(self, incident_id: str, service_name: str, alert_name: str,
                     analysis: str, proposed_action: dict, status: str = "Resolved Plan Generated"):
        """Logs a completed agent reasoning cycle into the history database."""
        try:
            table = self._get_table()
            tool = proposed_action.get("tool", "unknown")
            now = datetime.utcnow().isoformat()
            
            table.put_item(
                Item={
                    'incident_id': str(incident_id),
                    'timestamp': str(now),
                    'service_name': str(service_name),
                    'alert_name': str(alert_name),
                    'analysis': str(analysis),
                    'proposed_tool': str(tool),
                    'action_parameters': json.dumps(proposed_action.get("parameters", {})),
                    'status': str(status),
                    'pir_report': ""
                }
            )
            logger.info(f"Successfully logged incident {incident_id} to DynamoDB history.")
        except Exception as e:
            logger.error(f"Failed to log incident: {e}")

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single incident by its incident_id."""
        try:
            table = self._get_table()
            response = table.get_item(Key={'incident_id': str(incident_id)})
            item = response.get('Item')
            
            if item and isinstance(item.get('action_parameters'), str):
                try:
                    item['action_parameters'] = json.loads(item['action_parameters'])
                except json.JSONDecodeError:
                    pass
            return item
        except Exception as e:
            logger.error(f"Failed to fetch incident {incident_id}: {e}")
        return None

    def save_pir(self, incident_id: str, report: str):
        """Saves a generated Post-Incident Report to the incident record."""
        try:
            table = self._get_table()
            table.update_item(
                Key={'incident_id': str(incident_id)},
                UpdateExpression="set pir_report = :r",
                ExpressionAttributeValues={':r': str(report)},
                ReturnValues="UPDATED_NEW"
            )
            logger.info(f"Saved PIR for incident {incident_id} in DynamoDB.")
        except Exception as e:
            logger.error(f"Failed to save PIR for {incident_id}: {e}")

    def get_recent_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves the most recent incidents formatted for the frontend dashboard."""
        try:
            table = self._get_table()
            # Simplest approach: Scan and sort in memory for the demo
            response = table.scan()
            items = response.get('Items', [])
            
            items.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            items = items[:limit]

            for item in items:
                if isinstance(item.get('action_parameters'), str):
                    try:
                        item['action_parameters'] = json.loads(item['action_parameters'])
                    except json.JSONDecodeError:
                        pass

            return items
        except Exception as e:
            logger.error(f"Failed to fetch incident history: {e}")
            return []

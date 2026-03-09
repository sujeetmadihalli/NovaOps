#!/bin/bash
source venv/bin/activate
export PYTHONPATH=. 
uvicorn api.server:app --host 0.0.0.0 --port 8082 > test_api.log 2>&1 &
SERVER_PID=$!
echo "Waiting for uvicorn to start..."
sleep 5
echo "Sending payload..."
curl -X POST "http://localhost:8082/webhook/pagerduty" \
-H "Content-Type: application/json" \
-d '{
    "alert_name": "HighMemoryUsage_OOMKilled",
    "service_name": "dummy-service",
    "namespace": "default",
    "incident_id": "INC-AWS-Sim-200",
    "description": "Dummy service is crashing with OOMKilled in default namespace due to a memory leak."
}'
sleep 15
echo "Killing server..."
kill $SERVER_PID

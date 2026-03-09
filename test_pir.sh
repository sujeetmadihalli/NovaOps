#!/bin/bash
source venv/bin/activate
export PYTHONPATH=. 
uvicorn api.server:app --host 0.0.0.0 --port 8082 > test_pir.log 2>&1 &
SERVER_PID=$!
sleep 5
curl -X POST "http://localhost:8082/api/incidents/INC-AWS-Sim-200/report"
sleep 5
kill $SERVER_PID

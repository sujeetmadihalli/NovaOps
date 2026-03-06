#!/bin/bash
# Port forward Prometheus and the Dummy Service so the Host (and Agent) can talk to them

echo "Starting Port Forwards for the Hackathon Demo..."

echo "Forwarding Prometheus to port 9090..."
minikube kubectl -- port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090 > /dev/null 2>&1 &
PROM_PID=$!

echo "Forwarding Dummy Service to port 8080..."
minikube kubectl -- port-forward svc/dummy-service -n default 8080:8080 > /dev/null 2>&1 &
DUMMY_PID=$!

echo "Port Forwards are running."
echo "Prometheus: http://localhost:9090"
echo "Dummy Service: http://localhost:8080"
echo "Ready! In a new terminal, run: PYTHONPATH=. venv/bin/python evaluation_harness/multi_scenario_test.py"

# Wait for Ctrl+C
trap "kill $PROM_PID $DUMMY_PID" EXIT
wait

#!/bin/bash
set -e

echo "🚀 Starting Minikube to simulate production cluster..."
minikube start

export PATH="$PWD/bin:$PATH"

echo "🐳 Pointing Docker to Minikube daemon..."
eval $(minikube docker-env)

echo "📦 Building dummy-service..."
docker build -t dummy-service:latest ./dummy-service

echo "🚀 Deploying dummy-service to Kubernetes..."
kubectl apply -f dummy-service/k8s.yaml

echo "⏳ Waiting for dummy-service pod to be ready..."
kubectl wait --for=condition=ready pod -l app=dummy-service --timeout=120s

echo "🔌 Port forwarding local port 8080..."
kubectl port-forward svc/dummy-service 8080:8080 > /dev/null 2>&1 &
PF_PID=$!
sleep 5

echo "💥 Forcing Memory Leak (OOM) inside dummy-service..."
for i in {1..15}; do
  curl -s http://localhost:8080/memory-leak > /dev/null || true
  sleep 0.5
done
sleep 3

echo "💀 OOM Leak successful. dummy-service pod should be CrashLoop-ing now."
kill $PF_PID || true

echo "🕵️‍♀️  Starting Live NovaOps Agent to detect and analyze the OOM..."
./venv/bin/python run_live_agent.py

echo "🧹 Stopping Minikube..."
minikube stop

echo "🎉 Live simulation script entirely completed."

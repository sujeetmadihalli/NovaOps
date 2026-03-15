#!/bin/bash
set -e

# ==============================================================================
# NovaOps v2 — Global Start Script
# Spin up the entire system (Docker APIs + Minikube K8s) and pipe all stdout 
# to a single consolidated log file in the background.
# ==============================================================================

LOG_FILE="novaops_system.log"
PID_FILE=".system_pids"

# Clear out old logs and PIDs
rm -f "$LOG_FILE" "$PID_FILE"

echo "======================================" > "$LOG_FILE"
echo "    NovaOps System Logs - Started     " >> "$LOG_FILE"
echo "    Time: $(date)                     " >> "$LOG_FILE"
echo "======================================" >> "$LOG_FILE"

echo "🌟 Starting NovaOps System Ecosystem..."
echo "📂 All background logs are actively piping into: $LOG_FILE"
echo ""

# 1. Start Docker Backend (API + LocalStack)
echo "🐳 [1/2] Booting Backend API and AWS LocalStack (Docker)..."
docker compose up -d --build >> "$LOG_FILE" 2>&1

# Tail Docker logs in the background and append them to our global log stream
docker compose logs -f >> "$LOG_FILE" 2>&1 &
DOCKER_LOG_PID=$!
echo "$DOCKER_LOG_PID" >> "$PID_FILE"

# 2. Start Kubernetes Minikube
echo "🚀 [2/2] Booting Kubernetes Minikube Cluster..."
# We pipe minikube start to the background log so it doesn't clutter the terminal
minikube start >> "$LOG_FILE" 2>&1

echo ""
echo "✅ System is fully online and ready!"
echo "   - Dashboard UI:    http://localhost:8082/dashboard/"
echo "   - API Swagger      http://localhost:8082/docs"
echo "   - K8s Cluster:     minikube is running natively"
echo ""
echo "🔥 Want to see the merged logs? Run: tail -f $LOG_FILE"
echo "🛑 Want to shut down cleanly?  Run: ./stop_war_room.sh"
echo ""

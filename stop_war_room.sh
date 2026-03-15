#!/bin/bash

# ==============================================================================
# NovaOps v2 — Global Kill Switch
# Spin down the entire ecosystem and kill any background tail/log processes.
# ==============================================================================

echo "🛑 Initiating NovaOps System Shutdown..."

# 1. Kill background log tailing (pid list)
PID_FILE=".system_pids"
if [ -f "$PID_FILE" ]; then
    echo "🔪 Killing background logging tailing processes..."
    while IFS= read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# 2. Cleanly teardown Docker backend
echo "🐳 Stopping Docker containers and destroying backend network..."
docker compose down

# 3. Stop K8s Minikube
echo "🧹 Stopping Kubernetes Minikube cluster..."
minikube stop > /dev/null 2>&1 || true

# 4. Optional Cleanup (remove generated agent plans or DB histories for a fresh start later)
echo "🗑️  Removing old generated agent artifacts and history.db..."
rm -rf plans/ history.db 2>/dev/null || true

echo ""
echo "✅ System Offline. All resources released safely."

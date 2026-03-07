#!/bin/bash
# Unified Launch Script for NovaOps Demo Environment

# Color Codes
GREEN='\03---[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}       Starting NovaOps Demo Environment      ${NC}"
echo -e "${BLUE}==============================================${NC}"

# Pre-flight cleanup of orphaned ports
echo -e "${RED}[0/3] Sweeping orphaned ports from previous runs...${NC}"
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "python3 -m http.server" 2>/dev/null || true
pkill -f "kubectl -- port-forward" 2>/dev/null || true
pkill -f "kubectl port-forward" 2>/dev/null || true

for port in 8000 8080 8081 9090; do
    pid=$(lsof -t -i:$port 2>/dev/null)
    if [ ! -z "$pid" ]; then
        kill -9 $pid 2>/dev/null || true
    fi
done
sleep 1

# Initialize pristine log buffer
echo "--- NovaOps Session Started at $(date) ---" > novaops.log

# Start K8s Port Forwards
echo -e "${GREEN}[1/3] Forwarding Kubernetes telemetry ports...${NC}"
minikube kubectl -- port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090 2>&1 | awk '{ print "\033[0;33m[K8s-Prom]\033[0m  " $0 }' | tee -a novaops.log &
PROM_PID=$!
minikube kubectl -- port-forward svc/dummy-service -n default 8080:8080 2>&1 | awk '{ print "\033[0;33m[K8s-Dummy]\033[0m " $0 }' | tee -a novaops.log &
DUMMY_PID=$!
sleep 2

# Start FastAPI Webhook Server
echo -e "${GREEN}[2/3] Booting Event Gateway (FastAPI)...${NC}"
export PYTHONPATH=. 
venv/bin/uvicorn api.server:app --reload --port 8000 2>&1 | awk '{ print "\033[0;35m[Event-API]\033[0m " $0 }' | tee -a novaops.log &
API_PID=$!
sleep 3

# Start UI Dashboard Server
echo -e "${GREEN}[3/3] Booting UI Dashboard Engine...${NC}"
python3 -m http.server 8081 --directory dashboard 2>&1 | awk '{ print "\033[0;36m[Dashboard]\033[0m " $0 }' | tee -a novaops.log &
UI_PID=$!
sleep 1

echo -e "\n${BLUE}==============================================${NC}"
echo -e "${GREEN}All systems operational!${NC}"
echo -e "Event Gateway: http://localhost:8000"
echo -e "UI Dashboard:  http://localhost:8081"
echo -e "K8s Telemetry: Linked"
echo -e "\n${RED}Press Ctrl+C to gracefully shut down the entire agent architecture.${NC}"
echo -e "${BLUE}==============================================${NC}\n"

# Stream all background logs directly to this terminal
wait -n

# Graceful cleanup on exit
cleanup() {
    echo -e "\n${RED}Shutting down NovaOps background processes...${NC}"
    kill $PROM_PID $DUMMY_PID $API_PID $UI_PID 2>/dev/null
    exit 0
}

trap cleanup EXIT INT TERM

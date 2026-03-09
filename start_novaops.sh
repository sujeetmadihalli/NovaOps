#!/bin/bash
# Unified Launch Script for NovaOps Demo Environment

# Color Codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}       Starting NovaOps Demo Environment      ${NC}"
echo -e "${BLUE}==============================================${NC}"

# 0. Check and start Minikube
echo -e "${YELLOW}[0/5] Checking Kubernetes Cluster (Minikube)...${NC}"
if ! minikube status >/dev/null 2>&1; then
    echo -e "${CYAN}Minikube is not running. Starting Minikube...${NC}"
    minikube start
    echo -e "${GREEN}Minikube started successfully.${NC}"
else
    echo -e "${GREEN}Minikube is already running.${NC}"
fi
echo ""

# Pre-flight cleanup of orphaned ports
echo -e "${RED}[1/5] Sweeping orphaned ports from previous runs...${NC}"
pkill -f "python3 -m http.server" 2>/dev/null || true
pkill -f "kubectl -- port-forward" 2>/dev/null || true
pkill -f "kubectl port-forward" 2>/dev/null || true

for port in 8081 9090; do
    pid=$(lsof -t -i:$port 2>/dev/null)
    if [ ! -z "$pid" ]; then
        kill -9 $pid 2>/dev/null || true
    fi
done
sleep 1

# Initialize pristine log buffer
echo "--- NovaOps Session Started at $(date) ---" > novaops.log

# 2. Start K8s Port Forwards
echo -e "${GREEN}[2/5] Forwarding Kubernetes telemetry ports...${NC}"
minikube kubectl -- port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090 2>&1 | awk '{ print "\033[0;33m[K8s-Prom]\033[0m  " $0 }' | tee -a novaops.log &
PROM_PID=$!
minikube kubectl -- port-forward svc/dummy-service -n default 8080:8080 2>&1 | awk '{ print "\033[0;33m[K8s-Dummy]\033[0m " $0 }' | tee -a novaops.log &
DUMMY_PID=$!
sleep 2

# 3. Boot Docker Stack (API + LocalStack)
echo -e "${YELLOW}[3/5] Starting Docker containers (API + LocalStack)...${NC}"
docker compose up -d --build 2>&1 | awk '{ print "\033[0;35m[Docker]\033[0m " $0 }' | tee -a novaops.log

# 4. Wait for API to become healthy
echo -e "${CYAN}[4/5] Waiting for Event Gateway to become healthy...${NC}"
API_READY=false
for i in $(seq 1 30); do
    if curl -s --max-time 2 http://localhost:8082/health > /dev/null 2>&1; then
        API_READY=true
        break
    fi
    sleep 2
done

if [ "$API_READY" = false ]; then
    echo -e "${RED}WARNING: Event Gateway did not become healthy in 60 seconds.${NC}"
    echo -e "${YELLOW}Check logs with: docker compose logs novaops-api${NC}"
fi

# 5. Start UI Dashboard Server
echo -e "${GREEN}[5/5] Booting UI Dashboard Engine...${NC}"
python3 -m http.server 8081 --directory dashboard 2>&1 | awk '{ print "\033[0;36m[Dashboard]\033[0m " $0 }' | tee -a novaops.log &
UI_PID=$!
sleep 1

# Graceful cleanup on exit
cleanup() {
    echo -e "\n${RED}Shutting down NovaOps background processes...${NC}"
    kill $PROM_PID $DUMMY_PID $UI_PID 2>/dev/null
    docker compose down 2>/dev/null
    exit 0
}

trap cleanup EXIT INT TERM

echo -e "\n${BLUE}==============================================${NC}"
echo -e "${GREEN}All systems operational!${NC}"
echo -e "Event Gateway: http://localhost:8082 (Docker)"
echo -e "UI Dashboard:  http://localhost:8081"
echo -e "DynamoDB:      http://localhost:8000 (Docker)"
echo -e "LocalStack S3: http://localhost:4566 (Docker)"
echo -e "K8s Telemetry: Linked"
echo -e "\n${RED}Press Ctrl+C to gracefully shut down the entire agent architecture.${NC}"
echo -e "${BLUE}==============================================${NC}\n"

# Stream all background logs and block until interrupted
tail -f novaops.log

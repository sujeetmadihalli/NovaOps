#!/bin/bash
# simulate_incident.sh
# All-in-one script to break dummy-service and send alert to NovaOps

set -e

# Configuration
SERVICE_NAME="dummy-service"
API_URL="http://localhost:8082"
LEAK_COUNT=5
LOCAL_FALLBACK_URL="http://localhost:8080"
MINIKUBE_URL_TIMEOUT_SEC=10

echo "=== NovaOps Incident Simulator ==="

# 1. Get the dummy-service URL from minikube
echo "Fetching $SERVICE_NAME URL from minikube..."
# Try to get URL, fall back to checking if minikube is even running
if ! minikube status > /dev/null 2>&1; then
    echo "ERROR: Minikube is not running. Please start it first."
    exit 1
fi

SVC_URL=""
if command -v timeout >/dev/null 2>&1; then
    SVC_URL=$(timeout "${MINIKUBE_URL_TIMEOUT_SEC}s" minikube service "$SERVICE_NAME" --url 2>/dev/null | head -n 1 || true)
else
    SVC_URL=$(minikube service "$SERVICE_NAME" --url 2>/dev/null | head -n 1 || true)
fi

if [ -z "$SVC_URL" ]; then
    echo "WARN: Could not resolve service URL via 'minikube service'."
    echo "Trying localhost fallback: $LOCAL_FALLBACK_URL (port-forward path)..."
    if curl -s --max-time 2 "$LOCAL_FALLBACK_URL/" > /dev/null 2>&1; then
        SVC_URL="$LOCAL_FALLBACK_URL"
    else
        echo "ERROR: Could not find $SERVICE_NAME endpoint."
        echo "Try: kubectl apply -f dummy-service/k8s.yaml"
        echo "Or ensure port-forward is active on $LOCAL_FALLBACK_URL"
        exit 1
    fi
fi

echo "Found $SERVICE_NAME at: $SVC_URL"

# 2. Break the service (trigger memory leak)
echo "Triggering memory leak ($LEAK_COUNT times)..."
for i in $(seq 1 $LEAK_COUNT); do
    echo "  Request $i/$LEAK_COUNT to $SVC_URL/memory-leak..."
    curl -s "$SVC_URL/memory-leak" > /dev/null || echo "  Warning: Request failed (maybe already OOM?)"
done

echo "Memory leak triggered."

# 3. Send the webhook alert
INC_ID="INC-SIM-$(date +%s)"
echo "Sending simulated alert to NovaOps (Incident ID: $INC_ID)..."

if ! curl -s --max-time 2 "$API_URL/health" > /dev/null 2>&1; then
    echo "ERROR: Cannot reach NovaOps Event Gateway at $API_URL"
    echo "Please ensure you have started the system with ./start_novaops.sh"
    exit 1
fi

PAYLOAD=$(cat <<EOF
{
  "alert_name": "HighMemoryUsage_OOMKilled",
  "service_name": "$SERVICE_NAME",
  "namespace": "default",
  "incident_id": "$INC_ID",
  "description": "Simulated OOM alert from all-in-one simulator script."
}
EOF
)

RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "$API_URL/webhook/pagerduty" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d':' -f2)

if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "202" ]; then
    echo "✅ Incident simulated and alert sent!"
    echo "Check your dashboard at http://localhost:8081 to watch the agent analyze the failure!"
else
    echo "❌ Failed to send alert (Status: $HTTP_STATUS)"
    echo "Response: $RESPONSE"
    exit 1
fi
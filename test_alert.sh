#!/bin/bash
# Simple script to trigger a test incident in NovaOps

API_URL="http://localhost:8082"

echo "=== NovaOps Single Alert Test ==="
echo "Checking if Event Gateway is up..."

if ! curl -s --max-time 2 $API_URL/health > /dev/null; then
    echo "ERROR: Cannot reach Event Gateway at $API_URL"
    echo "Please ensure you have started the system with ./start_novaops.sh"
    exit 1
fi

echo "Event Gateway is healthy."
echo ""

# Generate a unique incident ID using timestamp
INC_ID="INC-TEST-$(date +%s)"

echo "Sending simulated OOM alert (Incident ID: $INC_ID)..."

PAYLOAD=$(cat <<EOF
{
  "alert_name": "HighMemoryUsage_OOMKilled",
  "service_name": "dummy-service",
  "namespace": "default",
  "incident_id": "$INC_ID",
  "description": "Simulated test alert sent from test_alert.sh"
}
EOF
)

RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST $API_URL/webhook/pagerduty \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d':' -f2)
BODY=$(echo "$RESPONSE" | sed -e 's/HTTP_STATUS:.*//g')

if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "202" ]; then
    echo "✅ Alert accepted by NovaOps!"
    echo "Response: $BODY"
    echo ""
    echo "The agent will now process the alert."
    echo "Go to your dashboard at http://localhost:8081 to watch the incident appear!"
    echo "Or check the live telemetry logs in the terminal where you ran start_novaops.sh."
else
    echo "❌ Failed to send alert (Status: $HTTP_STATUS)"
    echo "Response: $BODY"
    exit 1
fi

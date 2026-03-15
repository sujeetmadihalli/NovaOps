#!/bin/bash
set -e

# ==============================================================================
# NovaOps v2 — Run Simulated Incidents
# Fire 7 deterministic baseline test cases into the AI pipeline (Offline/Mocked).
# ==============================================================================

echo "============================================================"
echo "    🧪 NovaOps - Simulated Test Cases Harness"
echo "============================================================"
echo "This will run 7 mocked incidents through the full War Room,"
echo "Jury, and Governance mechanisms without touching real clusters."
echo ""

# Ensure we're using the virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# We run this in Mock mode so it uses local files instead of real AWS/K8s endpoints, 
# although the Bedrock LLM calls are still real if credentials exist in .env.
export PYTHONPATH="."
export NOVAOPS_USE_MOCK="1"

# If the dashboard is running via Docker compose, it uses LocalStack (DynamoDB/S3).
# Write simulation incident history to the same backend so results show up in
# http://localhost:8082/dashboard/.
LOCALSTACK_URL="${LOCALSTACK_URL:-http://localhost:4566}"
if [ -z "${DYNAMODB_ENDPOINT:-}" ] && command -v curl >/dev/null 2>&1; then
    if curl -fsS "${LOCALSTACK_URL}/_localstack/health" >/dev/null 2>&1; then
        export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
        export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
        export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
        export AWS_EC2_METADATA_DISABLED=true
        export DYNAMODB_ENDPOINT="${LOCALSTACK_URL}"
        export S3_ENDPOINT="${LOCALSTACK_URL}"
        echo "🗄️  LocalStack detected at ${LOCALSTACK_URL} — writing incident history to DynamoDB for dashboard visibility."
    else
        echo "ℹ️  LocalStack not detected — simulation results will be written to local SQLite (history.db)."
    fi
fi

echo "🚀 Launching Evaluation Harness..."
python evaluation_harness/multi_scenario_test.py

echo ""
echo "✅ All 7 simulated incidents complete! Check the Dashboard to view their plans."

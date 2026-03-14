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

echo "🚀 Launching Evaluation Harness..."
python evaluation_harness/multi_scenario_test.py

echo ""
echo "✅ All 7 simulated incidents complete! Check the Dashboard to view their plans."

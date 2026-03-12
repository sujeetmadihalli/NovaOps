#!/usr/bin/env python3
"""
Simple test script to trigger incidents via the webhook API.
This works with v2's actual architecture (War Room + Jury + Convergence + Governance).
"""

import requests
import json
import time
import sys

API_BASE_URL = "http://localhost:8082"

test_incidents = [
    {
        "alert_name": "HighMemoryUsage",
        "service_name": "redis-cache",
        "namespace": "default",
        "incident_id": "INC-OOM-001",
        "description": "Memory usage spiked to 92% on redis-cache pod",
    },
    {
        "alert_name": "CrashLoopBackOff",
        "service_name": "api-service",
        "namespace": "default",
        "incident_id": "INC-CRASH-001",
        "description": "api-service pod in CrashLoopBackOff state",
    },
    {
        "alert_name": "HighCPUUsage",
        "service_name": "worker-pool",
        "namespace": "default",
        "incident_id": "INC-CPU-001",
        "description": "CPU usage sustained at 85% over 5 minutes",
    },
]

def trigger_incident(incident: dict):
    """Trigger an incident via the webhook API."""
    url = f"{API_BASE_URL}/webhook/pagerduty"

    try:
        print(f"\n📤 Triggering: {incident['alert_name']} ({incident['incident_id']})")
        response = requests.post(url, json=incident, timeout=5)

        if response.status_code == 202:
            print(f"✅ ACCEPTED - Background task started")
            return True
        else:
            print(f"❌ FAILED - Status {response.status_code}: {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ ERROR - Cannot connect to API at {url}")
        print(f"   Ensure the FastAPI server is running on port 8082:")
        print(f"   uvicorn api.server:app --reload --port 8082")
        return False
    except Exception as e:
        print(f"❌ ERROR - {str(e)}")
        return False

def check_incidents():
    """Check incident history."""
    url = f"{API_BASE_URL}/api/incidents"

    try:
        print(f"\n📋 Fetching incident history...")
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            incidents = response.json()
            print(f"✅ Found {len(incidents)} incidents:")
            for inc in incidents:
                print(f"   - {inc.get('alert_name', 'Unknown')} ({inc.get('incident_id', '?')})")
                print(f"     Status: {inc.get('execution_status', 'Unknown')}")
            return True
        else:
            print(f"❌ FAILED - Status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ ERROR - {str(e)}")
        return False

def main():
    print("=" * 60)
    print("NovaOps v2 — Test Incident Trigger")
    print("=" * 60)

    # Check if API is running
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=2)
        if response.status_code == 200:
            print(f"✅ API is running at {API_BASE_URL}")
        else:
            print(f"❌ API returned unexpected status: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to API at {API_BASE_URL}")
        print(f"\nStart the API server first:")
        print(f"  cd Music\\NovaOps-v2")
        print(f"  ./venv/Scripts/Activate.ps1")
        print(f"  $env:PYTHONPATH = '.'")
        print(f"  uvicorn api.server:app --reload --port 8082")
        return False

    # Trigger test incidents
    print(f"\n🚀 Triggering {len(test_incidents)} test incidents...")
    success_count = 0

    for incident in test_incidents:
        if trigger_incident(incident):
            success_count += 1
        time.sleep(1)  # Space out requests

    print(f"\n{'='*60}")
    print(f"✅ Triggered {success_count}/{len(test_incidents)} incidents successfully")
    print(f"{'='*60}")

    # Wait for processing
    print(f"\n⏳ Waiting for incidents to process (10 seconds)...")
    time.sleep(10)

    # Check results
    print(f"\n🔍 Checking incident status...")
    check_incidents()

    print(f"\n📊 View the dashboard:")
    print(f"   http://localhost:8081")
    print(f"\n📝 View API docs:")
    print(f"   http://localhost:8082/docs")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

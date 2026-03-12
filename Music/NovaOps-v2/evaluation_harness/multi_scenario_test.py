import os
import sys
import json
import time

# Add the parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation_harness.v2_harness import V2EvaluationHarness

class TeeLogger:
    """Mirrors stdout/stderr to the novaops.log buffer with color tags for the Dashboard."""
    def __init__(self, stream, filename, prefix=""):
        self.terminal = stream
        self.log_file = open(filename, "a", encoding="utf-8")
        self.prefix = prefix
        self.is_new_line = True

    def write(self, message):
        self.terminal.write(message)
        formatted = ""
        for char in message:
            if self.is_new_line and char != '\n':
                formatted += self.prefix
                self.is_new_line = False
            formatted += char
            if char == '\n':
                self.is_new_line = True
        self.log_file.write(formatted)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

sys.stdout = TeeLogger(sys.stdout, "novaops.log", prefix="\033[0;32m[Nova-Agent]\033[0m ")
sys.stderr = TeeLogger(sys.stderr, "novaops.log", prefix="\033[0;31m[Agent-Log]\033[0m ")


def run_test_scenario(harness: V2EvaluationHarness, scenario_name: str, service_name: str, mock_data: dict, expected_tool: str) -> dict:
    """
    Runs a specific mocked incident scenario through v2's dual-pipeline.

    Args:
        harness: V2EvaluationHarness instance
        scenario_name: Scenario name
        service_name: Service name
        mock_data: Mock sensor data
        expected_tool: Expected remediation tool

    Returns:
        Result dict with test status
    """
    # Run through harness adapter
    result = harness.run_test_scenario(scenario_name, service_name, mock_data, expected_tool)

    # Report result
    if result["status"] == "PASS":
        print(f"\n✅ PASS: Agent correctly chose '{result['tool_chosen']}' for {scenario_name}.")
    else:
        print(f"\n❌ FAIL: {result['reason']}")

    return result

def main():
    """
    Run all 7 test scenarios through v2's dual-pipeline.

    Scenarios test:
    1. OOM + Bad Deployment → rollback_deployment
    2. Traffic Surge (Black Friday) → scale_deployment
    3. Thread Deadlock → restart_pods
    4. Bad Credential Rotation → rollback_deployment
    5. Organic Cache Bloat (no deployment) → restart_pods
    6. Third-party Outage → noop_require_human
    7. Zero-shot CPU Spike (unknown) → scale_deployment
    """
    # ---------------------------------------------------------
    # SCENARIO 1: REDIS CACHE — BAD DEPLOYMENT OOM
    # Service: redis-cache
    # A developer bumped the Redis maxmemory to 10GB, blowing out the container limit.
    # ---------------------------------------------------------
    scenario_1 = {
        "metrics": {"cpu_utilization": "12%", "memory_usage_mb": 4500, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "OOMKilling", "message": "Memory cgroup out of memory: kill process redis-server", "timestamp": "Now"}],
        "logs": [
            {"timestamp": "Now", "message": "[FATAL] redis-server: Out of memory allocating 1073741824 bytes!"},
            {"timestamp": "Now", "message": "[ERROR] MISCONF Redis is configured to save RDB snapshots, but is not able to persist on disk."}
        ],
        "github": [{"sha": "a1b2c3", "author": "dev-alice", "message": "feat: Bump redis maxmemory to 10GB for session cache", "date": "10 mins ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 2: CHECKOUT API — TRAFFIC SURGE (BLACK FRIDAY)
    # Service: checkout-api
    # Organic traffic spike during a flash sale, no bad code deployed.
    # ---------------------------------------------------------
    scenario_2 = {
        "metrics": {"cpu_utilization": "99.2%", "memory_usage_mb": 680, "memory_limit_mb": 2048, "requests_per_second": 12500},
        "k8s_events": [
            {"type": "Warning", "reason": "FailedProbes", "message": "Liveness probe failed: HTTP probe failed with statuscode: 503", "timestamp": "Now"},
            {"type": "Warning", "reason": "Unhealthy", "message": "Readiness probe failed: connection refused", "timestamp": "Now"}
        ],
        "logs": [
            {"timestamp": "Now", "message": "[ERROR] Connection pool exhausted for /api/v2/checkout — 429 Too Many Requests"},
            {"timestamp": "Now", "message": "[WARN] Request queue depth: 8432. Shedding load."}
        ],
        "github": [{"sha": "x9y8z7", "author": "dev-bob", "message": "fix: typo in checkout button label", "date": "3 days ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 3: AUTH SERVICE — THREAD DEADLOCK
    # Service: auth-service
    # OAuth token refresh threads deadlocked each other. CPU is near zero but service is frozen.
    # ---------------------------------------------------------
    scenario_3 = {
        "metrics": {"cpu_utilization": "0.3%", "memory_usage_mb": 340, "memory_limit_mb": 2048},
        "k8s_events": [
            {"type": "Warning", "reason": "Unhealthy", "message": "Readiness probe failed: Get http://10.1.0.45:8080/healthz: context deadline exceeded", "timestamp": "Now"}
        ],
        "logs": [
            {"timestamp": "Now", "message": "[WARN] TokenRefreshThread-3 waiting to acquire lock on SessionStore held by TokenRefreshThread-1"},
            {"timestamp": "Now", "message": "[FATAL] Deadlock detected between TokenRefreshThread-1 and TokenRefreshThread-3. All login requests are blocked."}
        ],
        "github": [{"sha": "k3l4j5", "author": "dev-carol", "message": "docs: update SSO integration guide", "date": "1 week ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 4: INVENTORY DB — BAD CREDENTIAL ROTATION
    # Service: inventory-db
    # An SRE rotated database credentials but forgot to update the Kubernetes secret, causing instant CrashLoop.
    # ---------------------------------------------------------
    scenario_4 = {
        "metrics": {"cpu_utilization": "0%", "memory_usage_mb": 0, "memory_limit_mb": 4096},
        "k8s_events": [
            {"type": "Warning", "reason": "CrashLoopBackOff", "message": "Back-off restarting failed container inventory-db", "timestamp": "Now"},
            {"type": "Warning", "reason": "Failed", "message": "Error: container inventory-db exited with code 1", "timestamp": "Now"}
        ],
        "logs": [
            {"timestamp": "Now", "message": "[FATAL] psycopg2.OperationalError: FATAL: password authentication failed for user 'inventory_rw'"},
            {"timestamp": "Now", "message": "[ERROR] Application startup failed — cannot establish connection to PostgreSQL at inventory-rds.internal:5432"}
        ],
        "github": [{"sha": "p0q1w2", "author": "sre-dave", "message": "chore: rotate database credentials for inventory-rds compliance audit", "date": "3 mins ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 5: ORDER PROCESSOR — ORGANIC CACHE BLOAT (NO DEPLOYMENT)
    # Service: order-processor
    # Months-old code slowly accumulated a bloated in-memory order cache. No recent deployments.
    # ---------------------------------------------------------
    scenario_5 = {
        "metrics": {"cpu_utilization": "35%", "memory_usage_mb": 4090, "memory_limit_mb": 4096},
        "k8s_events": [{"type": "Warning", "reason": "OOMKilling", "message": "Memory cgroup out of memory: kill process order-worker", "timestamp": "Now"}],
        "logs": [
            {"timestamp": "Now", "message": "[ERROR] OrderCache.size() = 2,847,331 entries — exceeds safe threshold of 500,000"},
            {"timestamp": "Now", "message": "[FATAL] java.lang.OutOfMemoryError: GC overhead limit exceeded"}
        ],
        "github": [{"sha": "z9x8c7", "author": "dev-eve", "message": "feat: initial order-processor microservice", "date": "4 months ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 6: NOTIFICATION SERVICE — THIRD-PARTY SMS OUTAGE
    # Service: notification-service
    # Twilio SMS API is completely down. Nothing we can fix internally.
    # ---------------------------------------------------------
    scenario_6 = {
        "metrics": {"cpu_utilization": "8%", "memory_usage_mb": 210, "memory_limit_mb": 2048},
        "k8s_events": [],
        "logs": [
            {"timestamp": "Now", "message": "[ERROR] TwilioRestException: HTTP 503 from https://api.twilio.com/2010-04-01/Messages.json — Service Unavailable"},
            {"timestamp": "Now", "message": "[ERROR] Failed to deliver OTP to +1-555-0142. SMS gateway unreachable. Retry 3/3 exhausted."},
            {"timestamp": "Now", "message": "[WARN] 847 pending SMS notifications queued. Delivery rate: 0/min."}
        ],
        "github": [{"sha": "m3n4b5", "author": "dev-frank", "message": "chore: update eslint config", "date": "2 days ago"}]
    }

    # ---------------------------------------------------------
    # SCENARIO 7: SEARCH INDEXER — ZERO-SHOT CPU SPIKE (NO RUNBOOK)
    # Service: search-indexer
    # Elasticsearch indexing workers are overwhelmed. Agent has NO runbook and must reason from scratch.
    # ---------------------------------------------------------
    scenario_7 = {
        "metrics": {"cpu_utilization": "98.7%", "memory_usage_mb": 1200, "memory_limit_mb": 4096, "requests_per_second": 9800},
        "k8s_events": [
            {"type": "Warning", "reason": "FailedProbes", "message": "Liveness probe failed: HTTP probe failed with statuscode: 504 Gateway Timeout", "timestamp": "Now"}
        ],
        "logs": [
            {"timestamp": "Now", "message": "[ERROR] ElasticsearchTimeoutException: 30s timeout on bulk index of 50,000 product documents"},
            {"timestamp": "Now", "message": "[WARN] Indexing queue backlog: 340,000 documents. Workers saturated."}
        ],
        "github": [{"sha": "q7w8e9", "author": "dev-grace", "message": "fix: correct typo in search result snippet", "date": "5 days ago"}]
    }

    print("="*70)
    print("STARTING BATCH EVALUATION")
    print("Testing NovaOps v2 dual-pipeline across 7 diverse incident scenarios")
    print("="*70)

    # Initialize harness (use mock mode by default)
    harness = V2EvaluationHarness(use_mock=True)
    results = []

    # Run all scenarios
    results.append(run_test_scenario(harness, "Redis Cache OOM — Bad Deployment",           "redis-cache",           scenario_1, expected_tool="rollback_deployment"))
    time.sleep(2)
    results.append(run_test_scenario(harness, "Checkout API — Black Friday Traffic Surge",   "checkout-api",          scenario_2, expected_tool="scale_deployment"))
    time.sleep(2)
    results.append(run_test_scenario(harness, "Auth Service — OAuth Thread Deadlock",        "auth-service",          scenario_3, expected_tool="restart_pods"))
    time.sleep(2)
    results.append(run_test_scenario(harness, "Inventory DB — Bad Credential Rotation",      "inventory-db",          scenario_4, expected_tool="rollback_deployment"))
    time.sleep(2)
    results.append(run_test_scenario(harness, "Order Processor — Organic Cache Bloat",       "order-processor",       scenario_5, expected_tool="restart_pods"))
    time.sleep(2)
    results.append(run_test_scenario(harness, "Notification Service — Twilio SMS Outage",    "notification-service",  scenario_6, expected_tool="noop_require_human"))
    time.sleep(2)
    results.append(run_test_scenario(harness, "Search Indexer — Zero-Shot CPU Spike",        "search-indexer",        scenario_7, expected_tool="scale_deployment"))

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    print(f"\nResults: {passed}/{total} scenarios PASSED\n")
    for r in results:
        status_icon = "✅" if r["status"] == "PASS" else "❌"
        print(f"{status_icon} {r['scenario']}: {r['status']} ({r['tool_chosen']})")
    print(f"\nSuccess rate: {100.0 * passed / total:.1f}%")

if __name__ == "__main__":
    main()

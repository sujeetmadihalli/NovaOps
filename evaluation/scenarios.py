"""Evaluation scenarios — 15 incident types across all 6 domains.

Each scenario defines mock data that gets injected into aggregators
and the expected tool action for scoring.
"""

SCENARIOS = [
    # --- OOM Domain ---
    {
        "id": 1,
        "name": "Bad Deployment Memory Leak",
        "domain": "oom",
        "difficulty": "easy",
        "alert_text": "OutOfMemoryError: Java heap space on payment-service after deployment",
        "expected_tool": "rollback_deployment",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 45.0,
                "memory_usage_mb": 4500,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 85.0,
                "pod_restart_count": 12,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "OOMKilling", "message": "Memory cgroup out of memory: Killed process", "timestamp": "2026-03-07T10:50:00Z"},
                {"type": "Warning", "reason": "BackOff", "message": "Back-off restarting failed container", "timestamp": "2026-03-07T10:51:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[FATAL] payment-service: OutOfMemoryError: Java heap space"},
                {"timestamp": 1741330140000, "message": "[ERROR] payment-service: GC overhead limit exceeded"},
            ],
            "github": [
                {"sha": "a1b2c3d4e5f6", "author": "dev-engineer", "message": "feat: Bump cache size to 10GB", "date": "2026-03-07T10:30:00Z"},
            ],
        },
    },
    {
        "id": 2,
        "name": "Organic Cache Bloat OOM (No Deploy)",
        "domain": "oom",
        "difficulty": "hard",
        "alert_text": "OutOfMemoryError on payment-service, no recent deployments",
        "expected_tool": "restart_pods",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 30.0,
                "memory_usage_mb": 4096,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 60.0,
                "pod_restart_count": 5,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "OOMKilling", "message": "Memory cgroup out of memory", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[FATAL] payment-service: OutOfMemoryError: Java heap space"},
            ],
            "github": [
                {"sha": "z9x8c7v6b5", "author": "dev", "message": "feat: initial commit", "date": "2025-11-01T10:00:00Z"},
            ],
        },
    },
    {
        "id": 3,
        "name": "Memory Leak with Red Herring Deploy",
        "domain": "oom",
        "difficulty": "hard",
        "alert_text": "OOM on payment-service, recent deploy was readme change only",
        "expected_tool": "restart_pods",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 25.0,
                "memory_usage_mb": 4096,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 40.0,
                "pod_restart_count": 3,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "OOMKilling", "message": "Memory cgroup out of memory", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[FATAL] payment-service: OutOfMemoryError: Java heap space"},
                {"timestamp": 1741329600000, "message": "[WARN] payment-service: Memory usage growing steadily over past 72 hours"},
            ],
            "github": [
                {"sha": "r3d-h3rr1ng", "author": "dev", "message": "docs: fix typo in README", "date": "2026-03-07T09:00:00Z"},
            ],
        },
    },

    # --- Traffic Surge Domain ---
    {
        "id": 4,
        "name": "Traffic Surge CPU Exhaustion",
        "domain": "traffic_surge",
        "difficulty": "easy",
        "alert_text": "CPU exhaustion on payment-service, ThreadPoolExecutor exhausted, Rejecting requests",
        "expected_tool": "scale_deployment",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 99.9,
                "memory_usage_mb": 500,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 75.0,
                "pod_restart_count": 0,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "FailedProbes", "message": "Liveness probe failed: HTTP timeout", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[ERROR] payment-service: ThreadPoolExecutor exhausted. Rejecting requests."},
            ],
            "github": [
                {"sha": "x9y8z7w6", "author": "dev", "message": "fix: typo in readme", "date": "2026-03-04T10:00:00Z"},
            ],
        },
    },
    {
        "id": 5,
        "name": "Zero-Shot Traffic Surge (No Runbook)",
        "domain": "traffic_surge",
        "difficulty": "hard",
        "alert_text": "Liveness probe failed on payment-service, CPU at 99%, requests timing out",
        "expected_tool": "scale_deployment",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 99.5,
                "memory_usage_mb": 600,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 90.0,
                "pod_restart_count": 2,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "FailedProbes", "message": "Liveness probe failed: HTTP timeout", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[ERROR] payment-service: Request timeout after 30s. Queue depth: 5000"},
            ],
            "github": [
                {"sha": "n0d3pl0y", "author": "dev", "message": "fix: update docs", "date": "2026-03-01T10:00:00Z"},
            ],
        },
    },

    # --- Deadlock Domain ---
    {
        "id": 6,
        "name": "Thread Deadlock Freeze",
        "domain": "deadlock",
        "difficulty": "medium",
        "alert_text": "Deadlock detected on payment-service, 0% CPU, Readiness probe failed",
        "expected_tool": "restart_pods",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 0.1,
                "memory_usage_mb": 200,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 100.0,
                "pod_restart_count": 0,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "Unhealthy", "message": "Readiness probe failed", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[WARN] Thread 4 waiting to acquire lock held by Thread 2"},
                {"timestamp": 1741330260000, "message": "[FATAL] Deadlock detected between Thread 2 and Thread 4"},
            ],
            "github": [
                {"sha": "k3l4j5h6", "author": "dev", "message": "docs: update wiki", "date": "2026-02-28T10:00:00Z"},
            ],
        },
    },
    {
        "id": 7,
        "name": "Partial Deadlock (Some Pods OK)",
        "domain": "deadlock",
        "difficulty": "medium",
        "alert_text": "Deadlock detected on payment-service pod-3, other pods healthy",
        "expected_tool": "restart_pods",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 15.0,
                "memory_usage_mb": 500,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 33.0,
                "pod_restart_count": 0,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "Unhealthy", "message": "Readiness probe failed for pod-3", "timestamp": "2026-03-07T10:50:00Z"},
                {"type": "Normal", "reason": "Started", "message": "pod-1 and pod-2 healthy", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[FATAL] pod-3: Deadlock detected. Thread waiting on lock."},
            ],
            "github": [],
        },
    },

    # --- Config Drift Domain ---
    {
        "id": 8,
        "name": "Bad DB Config Deployment Crash",
        "domain": "config_drift",
        "difficulty": "medium",
        "alert_text": "CrashLoopBackOff on payment-service after config change, ConnectionRefused to database",
        "expected_tool": "rollback_deployment",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 0.0,
                "memory_usage_mb": 0,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 100.0,
                "pod_restart_count": 20,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "CrashLoopBackOff", "message": "Back-off restarting failed container", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[FATAL] SQLException: Access Denied for user 'admin' (using password: NO)"},
            ],
            "github": [
                {"sha": "p0q1w2e3", "author": "sre", "message": "chore: update database connection string environment variables", "date": "2026-03-07T10:45:00Z"},
            ],
        },
    },
    {
        "id": 9,
        "name": "Secret Rotation Failure",
        "domain": "config_drift",
        "difficulty": "hard",
        "alert_text": "CrashLoopBackOff on payment-service, Access Denied after secret rotation",
        "expected_tool": "noop_require_human",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 0.0,
                "memory_usage_mb": 0,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 100.0,
                "pod_restart_count": 15,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "CrashLoopBackOff", "message": "Back-off restarting failed container", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[FATAL] Access Denied: authentication token expired after rotation"},
            ],
            "github": [],
        },
    },
    {
        "id": 10,
        "name": "Feature Flag Misconfiguration",
        "domain": "config_drift",
        "difficulty": "medium",
        "alert_text": "payment-service CrashLoopBackOff after feature flag change, configuration error",
        "expected_tool": "rollback_deployment",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 5.0,
                "memory_usage_mb": 100,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 100.0,
                "pod_restart_count": 8,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "CrashLoopBackOff", "message": "Container crash due to invalid config", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[FATAL] ConfigurationError: Unknown feature flag 'enable_v3_checkout' in config"},
            ],
            "github": [
                {"sha": "f1a9c0nf", "author": "pm", "message": "feat: enable v3 checkout feature flag", "date": "2026-03-07T10:40:00Z"},
            ],
        },
    },

    # --- Dependency Failure Domain ---
    {
        "id": 11,
        "name": "Third-Party API Outage",
        "domain": "dependency_failure",
        "difficulty": "medium",
        "alert_text": "UnknownHostException: third-party API api.vendor.com unreachable",
        "expected_tool": "noop_require_human",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 5.0,
                "memory_usage_mb": 100,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 50.0,
                "pod_restart_count": 0,
            },
            "k8s_events": [],
            "logs": [
                {"timestamp": 1741330200000, "message": "[ERROR] UnknownHostException: api.thirdparty-vendor.com Name or service not known"},
            ],
            "github": [
                {"sha": "m3n4b5v6", "author": "dev", "message": "chore: linting", "date": "2026-03-06T10:00:00Z"},
            ],
        },
    },
    {
        "id": 12,
        "name": "DNS Resolution Failure",
        "domain": "dependency_failure",
        "difficulty": "medium",
        "alert_text": "DNS resolution failed for internal service, upstream timeout on payment-service",
        "expected_tool": "noop_require_human",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 10.0,
                "memory_usage_mb": 200,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 80.0,
                "pod_restart_count": 0,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "DNSError", "message": "Failed to resolve order-service.svc.cluster.local", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[ERROR] DNS resolution failed: order-service.svc.cluster.local NXDOMAIN"},
            ],
            "github": [],
        },
    },

    # --- Cascading Failure Domain ---
    {
        "id": 13,
        "name": "Service A Down Cascading to B",
        "domain": "cascading_failure",
        "difficulty": "hard",
        "alert_text": "multiple services failing, connection pool exhausted on payment-service due to downstream timeout",
        "expected_tool": "noop_require_human",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 95.0,
                "memory_usage_mb": 3500,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 90.0,
                "pod_restart_count": 3,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "Unhealthy", "message": "Readiness probe failed: connection pool exhausted", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[ERROR] Connection pool exhausted waiting for order-service response"},
                {"timestamp": 1741330260000, "message": "[ERROR] Circuit breaker OPEN for order-service after 50 failures"},
            ],
            "github": [],
        },
    },
    {
        "id": 14,
        "name": "DB Connection Pool Exhausted",
        "domain": "cascading_failure",
        "difficulty": "hard",
        "alert_text": "connection pool exhausted on payment-service, cascade affecting multiple services",
        "expected_tool": "restart_pods",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 80.0,
                "memory_usage_mb": 3000,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 95.0,
                "pod_restart_count": 0,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "Unhealthy", "message": "All DB connections in use, cannot acquire new connection", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[ERROR] Cannot acquire connection from pool: all 100 connections in use"},
                {"timestamp": 1741330260000, "message": "[ERROR] downstream timeout from inventory-service"},
            ],
            "github": [],
        },
    },
    {
        "id": 15,
        "name": "Gradual Degradation Slow Leak",
        "domain": "traffic_surge",
        "difficulty": "hard",
        "alert_text": "Gradual CPU increase on payment-service, request timeout errors increasing, traffic spike detected",
        "expected_tool": "scale_deployment",
        "mock_data": {
            "metrics": {
                "cpu_utilization_percent": 88.0,
                "memory_usage_mb": 2500,
                "memory_limit_mb": 4096,
                "error_rate_5xx_percent": 25.0,
                "pod_restart_count": 0,
            },
            "k8s_events": [
                {"type": "Warning", "reason": "FailedProbes", "message": "Readiness probe intermittently failing", "timestamp": "2026-03-07T10:50:00Z"},
            ],
            "logs": [
                {"timestamp": 1741330200000, "message": "[WARN] Request latency P99 increased from 200ms to 1500ms"},
                {"timestamp": 1741330260000, "message": "[ERROR] Request timeout after 30s for /api/checkout"},
            ],
            "github": [],
        },
    },
]
